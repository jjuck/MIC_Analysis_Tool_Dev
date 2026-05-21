from __future__ import annotations

import argparse
from pathlib import Path
import time

from PIL import Image, ImageGrab
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
    parser.add_argument('--wait-ms', type=int, default=1200)
    args = parser.parse_args()

    workbook_path = Path(args.workbook_path).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    pythoncom.CoInitialize()
    excel = win32com.client.DispatchEx('Excel.Application')
    excel.Visible = True
    excel.DisplayAlerts = False
    excel.ScreenUpdating = True

    try:
        workbook = excel.Workbooks.Open(str(workbook_path))
        try:
            for index, sheet in enumerate(workbook.Worksheets, start=1):
                sheet.Activate()
                window = excel.ActiveWindow
                window.Zoom = 75
                used_range = sheet.UsedRange
                used_range.CopyPicture(Appearance=1, Format=2)
                time.sleep(args.wait_ms / 1000)
                clipboard_data = ImageGrab.grabclipboard()
                if clipboard_data is None or not isinstance(clipboard_data, Image.Image):
                    print(f'CAPTURE_FAILED=sheet_{index:02d}')
                    continue
                image_path = output_dir / f'sheet_{index:02d}_{safe_name(sheet.Name)}.png'
                clipboard_data.save(image_path)
                print(f'CAPTURED=sheet_{index:02d}')
        finally:
            workbook.Close(False)
    finally:
        excel.Quit()
        pythoncom.CoUninitialize()

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
