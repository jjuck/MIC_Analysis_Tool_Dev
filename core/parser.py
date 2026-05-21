from __future__ import annotations

import hashlib
import io
from functools import lru_cache

import chardet
import pandas as pd

from config.specs import ProductCatalog
from core.domain import ProductDetection, UploadedLog


_READER_CACHE_MAX = 4
_DETECTION_CACHE_MAX = 16
_READER_CACHE: dict[str, pd.DataFrame] = {}
_DETECTION_CACHE: dict[str, ProductDetection] = {}


def _prune_cache(cache: dict, max_size: int) -> None:
    while len(cache) > max_size:
        cache.pop(next(iter(cache)))


def _read_uploaded_bytes(uploaded_file) -> bytes:
    if hasattr(uploaded_file, "getvalue"):
        return uploaded_file.getvalue()
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    return uploaded_file.read()


def _bytes_signature(raw_bytes: bytes) -> str:
    return hashlib.sha1(raw_bytes).hexdigest()


def dataframe_cache_key(df: pd.DataFrame) -> str:
    cached_key = df.attrs.get("_mic_df_cache_key")
    if cached_key:
        return cached_key

    hashed_bytes = pd.util.hash_pandas_object(df, index=True, categorize=False).values.tobytes()
    cache_key = f"frame:{hashlib.sha1(hashed_bytes).hexdigest()}:{df.shape[0]}x{df.shape[1]}"
    df.attrs["_mic_df_cache_key"] = cache_key
    return cache_key


def source_file_names(df: pd.DataFrame) -> tuple[str, ...]:
    raw_names = df.attrs.get("_mic_source_file_names", ())
    return tuple(str(name) for name in raw_names)


def source_file_names_signature(df: pd.DataFrame) -> str:
    return "|".join(source_file_names(df))


def _normalize_signature_value(value) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped == "":
            return ""
        try:
            return f"{float(stripped):.12g}"
        except ValueError:
            return stripped
    try:
        return f"{float(value):.12g}"
    except (TypeError, ValueError):
        return str(value).strip()


def _normalize_column_name(column_name) -> str:
    normalized = str(column_name).strip()
    if normalized == "":
        return ""

    parts = normalized.split(".")
    if not parts[0].isdigit():
        return normalized

    base = str(int(parts[0]))
    if len(parts) == 1:
        return base

    suffix_parts = parts[1:]
    while suffix_parts and suffix_parts[0].isdigit() and int(suffix_parts[0]) == 0:
        suffix_parts = suffix_parts[1:]

    if not suffix_parts:
        return base

    return f"{base}.{'.'.join(suffix_parts)}"


def column_signature(df: pd.DataFrame) -> tuple[str, ...]:
    return tuple(_normalize_column_name(column) for column in df.columns)


def limit_row_signature(limit_row: pd.Series) -> tuple[str, ...]:
    return tuple(_normalize_signature_value(value) for value in limit_row.tolist())


def clean_sn(val):
    if pd.isna(val):
        return ""
    return str(val).replace('"', '').replace("'", "").replace('\t', '').strip()


@lru_cache(maxsize=128)
def _cached_freq_values(cols: tuple[str, ...]) -> tuple[float, ...]:
    return tuple(float(str(c).split('.')[0]) for c in cols)


def get_freq_values(cols):
    return list(_cached_freq_values(tuple(str(c) for c in cols)))


def build_uploaded_log(df: pd.DataFrame) -> UploadedLog:
    sn_column = df.columns[3]
    limit_low = df.iloc[0]
    limit_high = df.iloc[1]
    raw_test_data = df.iloc[2:].dropna(subset=[sn_column])
    test_data = raw_test_data[raw_test_data[sn_column].astype(str).str.contains('/', na=False)].reset_index(drop=True)
    return UploadedLog(
        df=df,
        sn_column=sn_column,
        limit_low=limit_low,
        limit_high=limit_high,
        test_data=test_data,
        source_file_names=source_file_names(df),
    )


class UploadedCsvReader:
    def read(self, uploaded_file):
        raw_bytes = _read_uploaded_bytes(uploaded_file)
        cache_key = f"upload:{_bytes_signature(raw_bytes)}"
        cached_df = _READER_CACHE.get(cache_key)
        if cached_df is not None:
            return cached_df

        detected_encoding = chardet.detect(raw_bytes).get("encoding")
        decoded = raw_bytes.decode(detected_encoding if detected_encoding else "utf-8-sig", errors="replace")
        df = pd.read_csv(io.StringIO(decoded), low_memory=False)
        df.columns = [_normalize_column_name(c) for c in df.columns]
        df.attrs["_mic_df_cache_key"] = cache_key

        _READER_CACHE[cache_key] = df
        _prune_cache(_READER_CACHE, _READER_CACHE_MAX)
        return df


class ProductDetector:
    def __init__(self, product_catalog: ProductCatalog):
        self._product_catalog = product_catalog

    def detect(self, df) -> ProductDetection:
        cache_key = dataframe_cache_key(df)
        cached_detection = _DETECTION_CACHE.get(cache_key)
        if cached_detection is not None:
            return cached_detection

        model_name = None
        prod_date = "Unknown"
        detected_pn = "Unknown"

        if df.shape[1] <= 3:
            detection = ProductDetection(model_name=model_name, prod_date=prod_date, detected_pn=detected_pn)
            _DETECTION_CACHE[cache_key] = detection
            _prune_cache(_DETECTION_CACHE, _DETECTION_CACHE_MAX)
            return detection

        for i in range(2, min(15, len(df))):
            sn_raw = clean_sn(df.iloc[i, 3])
            if "/" not in sn_raw:
                continue

            parts = sn_raw.split("/", 1)
            if len(parts) != 2:
                continue

            pn_part, sn_part = parts
            product_spec = self._product_catalog.detect_by_pn(pn_part)
            if product_spec is not None:
                model_name = product_spec.model_name
                detected_pn = pn_part

            if len(sn_part) >= 8:
                prod_date = f"20{sn_part[2:4]}/{sn_part[4:6]}/{sn_part[6:8]}"

            if model_name:
                break

        detection = ProductDetection(model_name=model_name, prod_date=prod_date, detected_pn=detected_pn)
        _DETECTION_CACHE[cache_key] = detection
        _prune_cache(_DETECTION_CACHE, _DETECTION_CACHE_MAX)
        return detection
