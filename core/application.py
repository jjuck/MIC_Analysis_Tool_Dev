from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from config.specs import LimitPolicy, ProductCatalog
from core.analyzer import AnalysisService
from core.domain import AnalysisReport, ProductDetection, UploadedLog
from core.parser import (
    ProductDetector,
    UploadedCsvReader,
    build_uploaded_log,
    column_signature,
    dataframe_cache_key,
    limit_row_signature,
    source_file_names_signature,
)


_ANALYSIS_CACHE_MAX = 8
_ANALYSIS_CACHE: dict[tuple[str, str, str, str, str, str], AnalysisReport] = {}


def _prune_cache(cache: dict, max_size: int) -> None:
    while len(cache) > max_size:
        cache.pop(next(iter(cache)))


class MultiFileAppendError(ValueError):
    pass


class UploadValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _PreparedUpload:
    file_name: str
    df: pd.DataFrame
    detection: ProductDetection
    uploaded_log: UploadedLog


class AnalysisApplicationService:
    def __init__(self, product_catalog: ProductCatalog, limit_policy: LimitPolicy):
        self._reader = UploadedCsvReader()
        self._detector = ProductDetector(product_catalog)
        self._analyzer = AnalysisService(limit_policy)
        self._product_catalog = product_catalog

    def read_dataframe(self, uploaded_file) -> pd.DataFrame:
        return self._reader.read(uploaded_file)

    def detect_product(self, df: pd.DataFrame) -> ProductDetection:
        return self._detector.detect(df)

    def prepare_uploaded_files(self, uploaded_files) -> tuple[pd.DataFrame, ProductDetection]:
        normalized_files = list(uploaded_files) if isinstance(uploaded_files, (list, tuple)) else [uploaded_files]
        if not normalized_files:
            raise UploadValidationError("업로드된 CSV 파일이 없습니다.")

        prepared_uploads = [self._prepare_single_upload(uploaded_file) for uploaded_file in normalized_files]
        for prepared in prepared_uploads:
            self._validate_sn_rows(prepared)
            self._validate_detected_layout(prepared)
        if len(prepared_uploads) == 1:
            prepared = prepared_uploads[0]
            return prepared.df, prepared.detection
        return self._merge_prepared_uploads(prepared_uploads)

    def analyze(self, df: pd.DataFrame, model_name: str, detection: ProductDetection) -> AnalysisReport:
        cache_key = (
            dataframe_cache_key(df),
            source_file_names_signature(df),
            model_name,
            detection.model_name or "",
            detection.prod_date,
            detection.detected_pn,
        )
        cached_report = _ANALYSIS_CACHE.get(cache_key)
        if cached_report is not None:
            return cached_report

        product_spec = self._product_catalog.get(model_name)
        self._validate_product_layout(df, product_spec.model_name)
        report = self._analyzer.analyze(df, product_spec, detection)
        _ANALYSIS_CACHE[cache_key] = report
        _prune_cache(_ANALYSIS_CACHE, _ANALYSIS_CACHE_MAX)
        return report

    def _prepare_single_upload(self, uploaded_file) -> _PreparedUpload:
        file_name = self._uploaded_file_name(uploaded_file)
        df = self.read_dataframe(uploaded_file).copy()
        df.attrs["_mic_source_file_names"] = (file_name,)
        detection = self.detect_product(df)
        uploaded_log = build_uploaded_log(df)
        return _PreparedUpload(file_name=file_name, df=df, detection=detection, uploaded_log=uploaded_log)

    def _merge_prepared_uploads(self, prepared_uploads: list[_PreparedUpload]) -> tuple[pd.DataFrame, ProductDetection]:
        base_upload = prepared_uploads[0]
        self._validate_detected_model(base_upload)

        base_columns = column_signature(base_upload.df)
        base_low = limit_row_signature(base_upload.uploaded_log.limit_low)
        base_high = limit_row_signature(base_upload.uploaded_log.limit_high)
        has_limit_row_mismatch = False

        for prepared in prepared_uploads[1:]:
            self._validate_detected_model(prepared)
            if prepared.detection.model_name != base_upload.detection.model_name:
                raise MultiFileAppendError(
                    f"동일 제품만 append할 수 있습니다. 기준 파일 [{base_upload.file_name}] 모델={base_upload.detection.model_name}, "
                    f"대상 파일 [{prepared.file_name}] 모델={prepared.detection.model_name}."
                )
            if column_signature(prepared.df) != base_columns:
                raise MultiFileAppendError(
                    f"파일 [{prepared.file_name}]의 컬럼 구조가 기준 파일 [{base_upload.file_name}]과 달라 append할 수 없습니다."
                )
            if limit_row_signature(prepared.uploaded_log.limit_low) != base_low or limit_row_signature(prepared.uploaded_log.limit_high) != base_high:
                has_limit_row_mismatch = True

        merged_df = pd.concat(
            [base_upload.df.iloc[:2].copy(), *(prepared.uploaded_log.test_data for prepared in prepared_uploads)],
            ignore_index=True,
        )
        merged_df.attrs["_mic_source_file_names"] = tuple(prepared.file_name for prepared in prepared_uploads)
        merged_detection = ProductDetection(
            model_name=base_upload.detection.model_name,
            prod_date=self._merge_prod_dates(tuple(prepared.detection.prod_date for prepared in prepared_uploads)),
            detected_pn=self._merge_part_numbers(tuple(prepared.detection.detected_pn for prepared in prepared_uploads)),
            has_limit_row_mismatch=has_limit_row_mismatch,
        )
        return merged_df, merged_detection

    def _validate_detected_model(self, prepared: _PreparedUpload) -> None:
        if prepared.detection.model_name:
            return
        raise MultiFileAppendError(self._unknown_model_message(prepared))

    def _validate_sn_rows(self, prepared: _PreparedUpload) -> None:
        if len(prepared.uploaded_log.test_data) > 0:
            return

        raise UploadValidationError(
            f"파일 [{prepared.file_name}]에서 분석 가능한 Serial Number 행을 찾지 못했습니다. "
            f"현재 SN 기준 컬럼은 [{prepared.uploaded_log.sn_column}]이며, 값에 'P/N/SN' 형식의 '/'가 포함되어야 합니다. "
            "CSV의 Serial Number가 비어 있거나 다른 컬럼에 기록된 파일은 분석할 수 없습니다."
        )

    def _validate_detected_layout(self, prepared: _PreparedUpload) -> None:
        if prepared.detection.model_name is None:
            return
        try:
            self._validate_product_layout(prepared.df, prepared.detection.model_name)
        except UploadValidationError as exc:
            raise UploadValidationError(
                f"파일 [{prepared.file_name}]의 P/N [{prepared.detection.detected_pn}]은 "
                f"[{prepared.detection.model_name}]로 감지되었지만, CSV 컬럼 레이아웃이 해당 제품 설정과 맞지 않습니다. {exc}"
            ) from exc

    def _validate_product_layout(self, df: pd.DataFrame, model_name: str) -> None:
        product_spec = self._product_catalog.get(model_name)
        for channel in product_spec.channels:
            missing_columns = max(channel.column_range) >= df.shape[1]
            if missing_columns:
                raise UploadValidationError(
                    f"[{model_name}]의 [{channel.name}] 채널 범위 {channel.column_range}를 읽을 수 없습니다. "
                    f"파일 컬럼 수는 {df.shape[1]}개입니다."
                )

            non_frequency_columns = []
            for column_name in df.columns[channel.column_range]:
                try:
                    float(str(column_name).split('.')[0])
                except ValueError:
                    non_frequency_columns.append(str(column_name))

            if non_frequency_columns:
                preview = ", ".join(non_frequency_columns[:5])
                raise UploadValidationError(
                    f"[{model_name}]의 [{channel.name}] 채널 주파수 범위에 비주파수 컬럼이 포함되어 있습니다: {preview}. "
                    "P/N과 실제 장비 로그 레이아웃이 다른 파일일 수 있습니다."
                )

    def _unknown_model_message(self, prepared: _PreparedUpload) -> str:
        return (
            f"파일 [{prepared.file_name}]에서 제품 모델을 판별하지 못했습니다. "
            f"현재 SN 기준 컬럼은 [{prepared.uploaded_log.sn_column}]이며, "
            "P/N/SN 형식의 Serial Number에서 제품 P/N을 감지합니다. "
            "SN 미기입, SN 컬럼 위치 변경, 또는 등록되지 않은 P/N인지 확인해 주세요."
        )

    def _merge_part_numbers(self, part_numbers: tuple[str, ...]) -> str:
        known_values = []
        for part_number in part_numbers:
            cleaned = part_number.strip()
            if cleaned and cleaned != "Unknown":
                known_values.append(cleaned)
        unique_values = tuple(dict.fromkeys(known_values))
        if not unique_values:
            return "Unknown"
        if len(unique_values) == 1:
            return unique_values[0]
        return "MULTI"

    def _merge_prod_dates(self, prod_dates: tuple[str, ...]) -> str:
        known_values = []
        for prod_date in prod_dates:
            cleaned = prod_date.strip()
            if cleaned and cleaned != "Unknown":
                known_values.append(cleaned)
        unique_values = tuple(dict.fromkeys(known_values))
        if not unique_values:
            return "Unknown"
        if len(unique_values) == 1:
            return unique_values[0]
        return ", ".join(unique_values)

    def _uploaded_file_name(self, uploaded_file) -> str:
        raw_name = getattr(uploaded_file, "name", "uploaded.csv")
        return str(raw_name).split("/")[-1].split("\\")[-1]
