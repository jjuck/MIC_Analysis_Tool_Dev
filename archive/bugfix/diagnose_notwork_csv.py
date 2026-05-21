import traceback
from pathlib import Path
import sys

import chardet
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

from config.limits import LIMIT_POLICY
from config.product_config import PRODUCT_CATALOG
from core.application import AnalysisApplicationService
from core.parser import ProductDetector, UploadedCsvReader, build_uploaded_log, column_signature, limit_row_signature


FILES = [
    "notwork_1.csv",
    "notwork_2.csv",
    "test_log/3903_head.csv",
    "test_log/3903_hy.csv",
]


def inspect_file(path: str) -> None:
    print(f"\n=== {path} ===")
    raw = open(path, "rb").read(4096)
    print("encoding:", chardet.detect(raw))
    try:
        class LocalUpload:
            name = path

            def getvalue(self):
                return open(path, "rb").read()

        df = UploadedCsvReader().read(LocalUpload())
        print("shape:", df.shape)
        print("columns[0:12]:", list(df.columns[:12]))
        print("columns[100:112]:", list(df.columns[100:112]) if df.shape[1] > 112 else "n/a")
        print("columns[200:225]:", list(df.columns[200:225]) if df.shape[1] > 225 else "n/a")
        for model_name in ("3903(LH Ecall)", "3203(LH non Ecall)"):
            product_spec = PRODUCT_CATALOG.get(model_name)
            print(f"configured_ranges[{model_name}]:")
            for channel in product_spec.channels:
                cols = list(df.columns[channel.column_range]) if df.shape[1] > max(channel.column_range) else []
                non_numeric = []
                for col in cols:
                    try:
                        float(str(col).split(".")[0])
                    except ValueError:
                        non_numeric.append(str(col))
                print("  ", channel.name, channel.column_range, "len=", len(cols), "non_numeric=", non_numeric[:8])

        slash_counts = []
        for col in df.columns:
            count = int(df[col].astype(str).str.contains("/", na=False).sum())
            if count:
                slash_counts.append((str(col), count, df[col].astype(str).str.contains("/", na=False).idxmax()))
        print("slash_columns_top10:", slash_counts[:10])
        for col, count, first_idx in slash_counts[:5]:
            print(f"slash_sample[{col}] row={first_idx}:", df.loc[first_idx, col])

        detector = ProductDetector(PRODUCT_CATALOG)
        detection = detector.detect(df)
        print("detection:", detection)

        uploaded_log = build_uploaded_log(df)
        print("sn_column:", uploaded_log.sn_column)
        print("test_data.shape:", uploaded_log.test_data.shape)
        print("sn_head:", uploaded_log.test_data[uploaded_log.sn_column].head(5).tolist())
        print("column_signature_len:", len(column_signature(df)))
        print("limit_low_signature_sample:", limit_row_signature(uploaded_log.limit_low)[:12])
        print("limit_high_signature_sample:", limit_row_signature(uploaded_log.limit_high)[:12])

        app = AnalysisApplicationService(PRODUCT_CATALOG, LIMIT_POLICY)
        report = app.analyze(df, "3903(LH Ecall)", detection)
        print("analyze: OK", "total_qty=", report.total_qty, "total_fail=", report.total_fail)
    except Exception as exc:
        print("ERROR:", type(exc).__name__, repr(exc))
        traceback.print_exc(limit=5)


for file_path in FILES:
    inspect_file(file_path)


class LocalUpload:
    def __init__(self, path: str):
        self.name = path

    def getvalue(self):
        return open(self.name, "rb").read()


print("\n=== prepare_uploaded_files combinations ===")
app = AnalysisApplicationService(PRODUCT_CATALOG, LIMIT_POLICY)
for group in (("notwork_1.csv",), ("notwork_2.csv",), ("notwork_1.csv", "notwork_2.csv")):
    print("\nFILES:", group)
    try:
        upload_arg = [LocalUpload(path) for path in group] if len(group) > 1 else LocalUpload(group[0])
        df, detection = app.prepare_uploaded_files(upload_arg)
        print("prepared:", df.shape, detection)
        model_name = detection.model_name or "3903(LH Ecall)"
        report = app.analyze(df, model_name, detection)
        print("report:", report.total_qty, report.total_fail)
    except Exception as exc:
        print("ERROR:", type(exc).__name__, repr(exc))
        traceback.print_exc(limit=5)
