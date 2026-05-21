from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from config.specs import ChannelSpec, LimitPolicy, ProductSpec
from core.domain import (
    AnalysisReport,
    ChannelAnalysis,
    ChannelStatistics,
    DefectSummary,
    MeasurementPoint,
    ProductDetection,
    SampleAnalysis,
    UploadedLog,
)
from core.parser import build_uploaded_log, clean_sn, dataframe_cache_key, get_freq_values, source_file_names_signature


_CONTEXT_CACHE_MAX = 16
_UPLOADED_LOG_CACHE_MAX = 8
_ANALYSIS_CACHE_MAX = 8
_CONTEXT_CACHE: dict[tuple[str, str], tuple[ChannelContext, ...]] = {}
_UPLOADED_LOG_CACHE: dict[str, UploadedLog] = {}
_ANALYSIS_CACHE: dict[tuple[str, str, str, str, str, str], AnalysisReport] = {}
_POINT_LABELS = ("200Hz", "1kHz", "4kHz")
_DEFECT_STATUSES = frozenset({"No Signal", "Curved Out", "Nan"})


def _prune_cache(cache: dict, max_size: int) -> None:
    while len(cache) > max_size:
        cache.pop(next(iter(cache)))


def _analysis_cache_key(df: pd.DataFrame, product_spec: ProductSpec, detection: ProductDetection) -> tuple[str, str, str, str, str, str]:
    return (
        dataframe_cache_key(df),
        source_file_names_signature(df),
        product_spec.model_name,
        detection.model_name or "",
        detection.prod_date,
        detection.detected_pn,
    )


def _to_numeric_frame(frame: pd.DataFrame) -> np.ndarray:
    return frame.apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float, copy=False)


def _to_numeric_series(series: pd.Series) -> np.ndarray:
    return pd.to_numeric(series, errors="coerce").to_numpy(dtype=float, copy=False)


@dataclass(frozen=True, slots=True)
class ChannelContext:
    channel_spec: ChannelSpec
    cols: pd.Index
    freqs: np.ndarray
    point_labels: tuple[str, ...]
    point_indices: np.ndarray
    point_columns: dict[str, str]
    other_indices: tuple[int, ...]
    center_1k_col: str
    no_signal_limit: float
    thd_limit: float | None


@dataclass(frozen=True, slots=True)
class PreparedChannelData:
    context: ChannelContext
    statuses: np.ndarray
    point_values: np.ndarray
    point_failures: np.ndarray
    thd_values: np.ndarray | None
    thd_failures: np.ndarray | None


class ChannelContextFactory:
    def __init__(self, limit_policy: LimitPolicy):
        self._limit_policy = limit_policy

    def build(self, df: pd.DataFrame, product_spec: ProductSpec) -> tuple[ChannelContext, ...]:
        cache_key = (dataframe_cache_key(df), product_spec.model_name)
        cached_contexts = _CONTEXT_CACHE.get(cache_key)
        if cached_contexts is not None:
            return cached_contexts

        contexts: list[ChannelContext] = []
        for channel in product_spec.channels:
            cols = df.columns[channel.column_range]
            freqs = np.array(get_freq_values(cols))
            point_indices = np.array([int(np.argmin(np.abs(freqs - point))) for point in self._limit_policy.check_points], dtype=int)
            other_indices = tuple(int(index) for index in np.setdiff1d(np.arange(len(cols)), point_indices))
            point_columns = {
                label: cols[point_index]
                for label, point_index in zip(_POINT_LABELS, point_indices)
            }
            contexts.append(
                ChannelContext(
                    channel_spec=channel,
                    cols=cols,
                    freqs=freqs,
                    point_labels=_POINT_LABELS,
                    point_indices=point_indices,
                    point_columns=point_columns,
                    other_indices=other_indices,
                    center_1k_col=point_columns["1kHz"],
                    no_signal_limit=self._limit_policy.no_signal_limit_for(channel.mic_type),
                    thd_limit=self._limit_policy.thd_limit_for(channel.mic_type) if channel.has_thd else None,
                )
            )
        context_tuple = tuple(contexts)
        _CONTEXT_CACHE[cache_key] = context_tuple
        _prune_cache(_CONTEXT_CACHE, _CONTEXT_CACHE_MAX)
        return context_tuple


class ChannelClassifier:
    def __init__(self, limit_policy: LimitPolicy):
        self._limit_policy = limit_policy

    def classify(self, values: np.ndarray, context: ChannelContext, low: np.ndarray, high: np.ndarray) -> np.ndarray:
        nan_rows = np.isnan(values).all(axis=1)
        fail_matrix = np.isnan(values) | (values < low) | (values > high)
        fail_rows = fail_matrix.any(axis=1)
        no_signal_rows = fail_rows & (values < context.no_signal_limit).any(axis=1)
        if context.other_indices:
            other_fail_rows = fail_matrix[:, context.other_indices].any(axis=1)
        else:
            other_fail_rows = np.zeros(values.shape[0], dtype=bool)
        margin_out_rows = fail_rows & ~nan_rows & ~no_signal_rows & ~other_fail_rows

        statuses = np.full(values.shape[0], "Curved Out", dtype=object)
        statuses[nan_rows] = "Nan"
        statuses[~nan_rows & ~fail_rows] = "Normal"
        statuses[no_signal_rows] = "No Signal"
        statuses[margin_out_rows] = "Margin Out"
        return statuses

    def build_channel_analysis(self, sample_index: int, prepared: PreparedChannelData) -> ChannelAnalysis:
        context = prepared.context
        points: dict[str, MeasurementPoint] = {}
        for point_index, label in enumerate(context.point_labels):
            value = prepared.point_values[sample_index, point_index]
            points[label] = MeasurementPoint(
                label=label,
                display_value=f"{value:.3f}" if not np.isnan(value) else "-",
                is_fail=bool(prepared.point_failures[sample_index, point_index]),
            )

        if prepared.thd_values is not None and prepared.thd_failures is not None:
            thd_value = prepared.thd_values[sample_index]
            points["THD"] = MeasurementPoint(
                label="THD",
                display_value=f"{thd_value:.3f}" if not np.isnan(thd_value) else "-",
                is_fail=bool(prepared.thd_failures[sample_index]),
            )
        else:
            points["THD"] = MeasurementPoint(label="THD", display_value="N/A", is_fail=False)

        status = str(prepared.statuses[sample_index])
        return ChannelAnalysis(mic_name=context.channel_spec.name, status=status, points=points)


class PreparedChannelFactory:
    def __init__(self, classifier: ChannelClassifier):
        self._classifier = classifier

    def build(self, uploaded_log: UploadedLog, contexts: tuple[ChannelContext, ...]) -> tuple[PreparedChannelData, ...]:
        prepared_channels: list[PreparedChannelData] = []
        for context in contexts:
            values = _to_numeric_frame(uploaded_log.test_data.loc[:, context.cols])
            low = _to_numeric_series(uploaded_log.limit_low.loc[context.cols])
            high = _to_numeric_series(uploaded_log.limit_high.loc[context.cols])
            statuses = self._classifier.classify(values, context, low, high)
            point_values = values[:, context.point_indices]
            point_low = low[context.point_indices]
            point_high = high[context.point_indices]
            point_failures = ~np.isnan(point_values) & ((point_values < point_low) | (point_values > point_high))

            thd_values: np.ndarray | None = None
            thd_failures: np.ndarray | None = None
            if context.channel_spec.has_thd and context.channel_spec.thd_column_index is not None and context.thd_limit is not None:
                thd_series = uploaded_log.test_data.iloc[:, context.channel_spec.thd_column_index]
                thd_values = _to_numeric_series(thd_series)
                thd_failures = ~np.isnan(thd_values) & ((thd_values < 0) | (thd_values > context.thd_limit))

            prepared_channels.append(
                PreparedChannelData(
                    context=context,
                    statuses=statuses,
                    point_values=point_values,
                    point_failures=point_failures,
                    thd_values=thd_values,
                    thd_failures=thd_failures,
                )
            )
        return tuple(prepared_channels)


class DefectSummaryService:
    def __init__(self, limit_policy: LimitPolicy):
        self._limit_policy = limit_policy
        self._priority_order = ("Curved Out", "No Signal", "Margin Out", "Nan")

    def build(self, samples: tuple[SampleAnalysis, ...], issue_indices: tuple[int, ...]) -> DefectSummary:
        counts = {defect_type: 0 for defect_type in self._limit_policy.defect_types}
        total_failure_samples = 0

        for idx in issue_indices:
            defect_type = samples[idx].primary_defect_status(self._priority_order)
            if defect_type in counts:
                counts[defect_type] += 1
                total_failure_samples += 1

        return DefectSummary(counts=counts, total_failure_samples=total_failure_samples)


class AnalysisService:
    def __init__(self, limit_policy: LimitPolicy):
        self._limit_policy = limit_policy
        self._context_factory = ChannelContextFactory(limit_policy)
        self._classifier = ChannelClassifier(limit_policy)
        self._prepared_channel_factory = PreparedChannelFactory(self._classifier)
        self._defect_summary_service = DefectSummaryService(limit_policy)

    def analyze(self, df: pd.DataFrame, product_spec: ProductSpec, detection: ProductDetection) -> AnalysisReport:
        cache_key = _analysis_cache_key(df, product_spec, detection)
        cached_report = _ANALYSIS_CACHE.get(cache_key)
        if cached_report is not None:
            return cached_report

        uploaded_log = self._build_uploaded_log(df)
        contexts = self._context_factory.build(df, product_spec)
        prepared_channels = self._prepared_channel_factory.build(uploaded_log, contexts)
        statistics = {channel.name: ChannelStatistics(channel.name) for channel in product_spec.channels}
        for prepared in prepared_channels:
            statistics[prepared.context.channel_spec.name].record_batch(
                prepared.statuses,
                prepared.context.point_labels,
                prepared.point_values,
            )

        serial_numbers = uploaded_log.test_data[uploaded_log.sn_column].map(clean_sn).tolist()
        samples: list[SampleAnalysis] = []
        issue_indices: list[int] = []
        stats_indices: list[int] = []
        plotting_normal_indices: list[int] = []

        for idx, serial_number in enumerate(serial_numbers):
            sample, is_issue, is_pure_normal, is_defect = self._build_sample_analysis(idx, serial_number, prepared_channels)
            samples.append(sample)
            if is_issue:
                issue_indices.append(idx)
            if is_pure_normal:
                plotting_normal_indices.append(idx)
            if not is_defect:
                stats_indices.append(idx)

        sample_tuple = tuple(samples)
        issue_index_tuple = tuple(issue_indices)
        defect_summary = self._defect_summary_service.build(sample_tuple, issue_index_tuple)
        report = AnalysisReport(
            detection=detection,
            product_spec=product_spec,
            uploaded_log=uploaded_log,
            samples=sample_tuple,
            issue_indices=issue_index_tuple,
            stats_indices=tuple(stats_indices),
            plotting_normal_indices=tuple(plotting_normal_indices),
            channel_statistics=tuple(statistics.values()),
            defect_summary=defect_summary,
        )
        _ANALYSIS_CACHE[cache_key] = report
        _prune_cache(_ANALYSIS_CACHE, _ANALYSIS_CACHE_MAX)
        return report

    def _build_uploaded_log(self, df: pd.DataFrame) -> UploadedLog:
        cache_key = dataframe_cache_key(df)
        cached_uploaded_log = _UPLOADED_LOG_CACHE.get(cache_key)
        if cached_uploaded_log is not None:
            return cached_uploaded_log

        uploaded_log = build_uploaded_log(df)
        _UPLOADED_LOG_CACHE[cache_key] = uploaded_log
        _prune_cache(_UPLOADED_LOG_CACHE, _UPLOADED_LOG_CACHE_MAX)
        return uploaded_log

    def _build_sample_analysis(
        self,
        index: int,
        serial_number: str,
        prepared_channels: tuple[PreparedChannelData, ...],
    ) -> tuple[SampleAnalysis, bool, bool, bool]:
        channel_analyses: list[ChannelAnalysis] = []
        is_issue = False
        is_pure_normal = True
        is_defect = False
        for prepared in prepared_channels:
            channel_analysis = self._classifier.build_channel_analysis(index, prepared)
            status = channel_analysis.status
            if status != "Normal":
                is_issue = True
                is_pure_normal = False
            if status in _DEFECT_STATUSES:
                is_defect = True
            channel_analyses.append(channel_analysis)

        return (
            SampleAnalysis(
                index=index,
                serial_number=serial_number,
                channels=tuple(channel_analyses),
            ),
            is_issue,
            is_pure_normal,
            is_defect,
        )
