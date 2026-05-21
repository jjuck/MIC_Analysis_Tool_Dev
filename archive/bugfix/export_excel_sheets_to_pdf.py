from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pythoncom
import win32com.client


def safe_name(name: str) -> str:
    invalid = '<>:"/\\|?*'
    for ch in invalid:
        name = name.replace(ch, '_')
    return name


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('workbook_path')
    parser.add_argument('output_dir')
    args = parser.parse_args()

    workbook_path = Path(args.workbook_path).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    pythoncom.CoInitialize()
    excel = win32com.client.DispatchEx('Excel.Application')
    excel.Visible = False
    excel.DisplayAlerts = False

    try:
        workbook = excel.Workbooks.Open(str(workbook_path))
        try:
            for index, sheet in enumerate(workbook.Worksheets, start=1):
                pdf_path = output_dir / f'sheet_{index:02d}_{safe_name(sheet.Name)}.pdf'
                sheet.ExportAsFixedFormat(0, str(pdf_path))
                print(f'PDF_CREATED=sheet_{index:02d}')
        finally:
            workbook.Close(False)
    finally:
        excel.Quit()
        pythoncom.CoUninitialize()

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
