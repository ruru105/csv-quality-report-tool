from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill


INPUT_FILE = Path("sample.csv")
OUTPUT_FILE = Path("report.xlsx")


def read_csv_safely(file_path):
    """UTF-8とWindows用の文字コードに対応してCSVを読み込む。"""
    for encoding in ("utf-8-sig", "cp932"):
        try:
            return pd.read_csv(file_path, encoding=encoding)
        except UnicodeDecodeError:
            continue

    raise ValueError("CSVの文字コードを判定できませんでした。")


def format_workbook(writer):
    """Excelレポートを読みやすく整える。"""
    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(color="FFFFFF", bold=True)

    for worksheet in writer.book.worksheets:
        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions

        for cell in worksheet[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")

        for column_cells in worksheet.columns:
            max_length = max(
                len(str(cell.value)) if cell.value is not None else 0
                for cell in column_cells
            )
            column_letter = column_cells[0].column_letter
            worksheet.column_dimensions[column_letter].width = min(
                max(max_length + 2, 12), 40
            )


def main():
    if not INPUT_FILE.exists():
        print(f"エラー：{INPUT_FILE} が見つかりません。")
        return

    data = read_csv_safely(INPUT_FILE)

    row_count = len(data)
    column_count = len(data.columns)
    missing_count = int(data.isna().sum().sum())
    duplicate_count = int(data.duplicated().sum())

    status = (
        "問題あり"
        if missing_count > 0 or duplicate_count > 0
        else "問題なし"
    )

    summary = pd.DataFrame(
        {
            "確認項目": [
                "データ件数",
                "列数",
                "欠損セル数",
                "重複件数",
                "総合判定",
            ],
            "結果": [
                row_count,
                column_count,
                missing_count,
                duplicate_count,
                status,
            ],
        }
    )

    column_info = pd.DataFrame(
        {
            "列名": data.columns,
            "データ型": [str(data[column].dtype) for column in data.columns],
            "有効データ数": [int(data[column].notna().sum()) for column in data.columns],
            "欠損数": [int(data[column].isna().sum()) for column in data.columns],
            "ユニーク数": [int(data[column].nunique(dropna=True)) for column in data.columns],
        }
    )

    missing_rows = data[data.isna().any(axis=1)]
    duplicate_rows = data[data.duplicated(keep=False)]

    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="検査結果", index=False)
        column_info.to_excel(writer, sheet_name="列情報", index=False)
        missing_rows.to_excel(writer, sheet_name="欠損行", index=False)
        duplicate_rows.to_excel(writer, sheet_name="重複行", index=False)
        data.to_excel(writer, sheet_name="元データ", index=False)

        format_workbook(writer)

    print(f"完了：{OUTPUT_FILE} を作成しました。")
    print(
        f"データ件数={row_count} / "
        f"欠損セル数={missing_count} / "
        f"重複件数={duplicate_count} / "
        f"判定={status}"
    )


if __name__ == "__main__":
    main()