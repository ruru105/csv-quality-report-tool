import argparse
import os
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill

from csv_rules import RulesError, evaluate_rules, load_rules


DEFAULT_INPUT_FILE = "sample.csv"
DEFAULT_OUTPUT_FILE = "report.xlsx"

# カンマ区切りとして読んだ結果が1列だけになったとき、
# 見出しにこれらの文字が含まれていれば、その文字を区切り文字として読み直す。
CANDIDATE_DELIMITERS = ["\t", ";", "|"]
# 先頭に0がある数字(007、0123など)。IDや郵便番号の先頭の0を守るために使う。
LEADING_ZERO_PATTERN = r"^[+-]?0\d"

# 総合判定のセルを目立たせる色(薄い塗りつぶし・濃い文字色)。
STATUS_STYLES = {
    "問題あり": {"fill": "FFC7CE", "font": "9C0006"},
    "問題なし": {"fill": "C6EFCE", "font": "006100"},
}


def parse_args(argv):
    """コマンドで指定された、検査するCSVと出力先を読み取る。"""
    parser = argparse.ArgumentParser(
        description="CSVファイルを検査して、結果をExcelレポートにまとめます。"
    )
    parser.add_argument(
        "input_file",
        nargs="?",
        default=DEFAULT_INPUT_FILE,
        help=f"検査するCSVファイル(省略すると {DEFAULT_INPUT_FILE})",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=DEFAULT_OUTPUT_FILE,
        help=f"作成するExcelファイル(省略すると {DEFAULT_OUTPUT_FILE})",
    )
    parser.add_argument(
        "-c",
        "--config",
        default=None,
        help="検査ルールを書いたJSONファイル(省略すると、すべての列を対象に検査します)",
    )
    return parser.parse_args(argv)


def is_same_file(first, second):
    """2つのパスが、同じファイルを指していればTrueを返す。

    書き方が違っても(./を付ける・フォルダをたどる・ハードリンクなど)、
    実体が同じなら同じものとして扱う。
    """
    if first.resolve() == second.resolve():
        return True
    return second.exists() and os.path.samefile(first, second)


def read_csv_safely(file_path, **read_options):
    """UTF-8とWindows用の文字コードに対応してCSVを読み込む。

    カンマ区切りとして読んだ結果、列が1つにまとまってしまったときは、
    見出しに含まれる記号(タブなど)から区切り文字を判断して読み直す。
    read_optionsには、pandasのread_csvに渡す追加の指定(dtype=strなど)を書ける。
    """
    for encoding in ("utf-8-sig", "cp932"):
        try:
            data = pd.read_csv(file_path, encoding=encoding, **read_options)
        except UnicodeDecodeError:
            continue

        return _reread_if_wrong_delimiter(data, file_path, encoding, read_options)

    raise ValueError("CSVの文字コードを判定できませんでした。")


def _reread_if_wrong_delimiter(data, file_path, encoding, read_options=None):
    """1列だけの読み込み結果を確認し、区切り文字の判定違いなら読み直す。"""
    if len(data.columns) != 1:
        return data

    header = str(data.columns[0])
    for delimiter in CANDIDATE_DELIMITERS:
        if delimiter in header:
            return pd.read_csv(
                file_path, encoding=encoding, sep=delimiter, **(read_options or {})
            )

    return data


def restore_leading_zeros(data, text):
    """先頭に0がある値(007など)を含む列は、元の文字のまま戻す。

    pandasは「007」を数値の7として読むため、そのままではIDの先頭の0が消える。
    先頭に0がある値を含む列だけ、CSVに書かれていた文字に置き換える(他の列は数値のまま)。
    """
    restored = data.copy()
    for column in text.columns:
        has_leading_zero = text[column].dropna().str.match(LEADING_ZERO_PATTERN).any()
        if has_leading_zero:
            restored[column] = text[column]
    return restored


def visual_width(text):
    """全角文字を2、半角文字を1として数えた、見た目の幅を返す。

    日本語の見出しは、文字数だけで列幅を決めると右端が切れることがあるため、
    見た目の幅で列幅を決める。
    """
    width = 0
    for char in text:
        width += 2 if unicodedata.east_asian_width(char) in ("F", "W") else 1
    return width


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
            max_width = max(
                visual_width(str(cell.value)) if cell.value is not None else 0
                for cell in column_cells
            )
            column_letter = column_cells[0].column_letter
            worksheet.column_dimensions[column_letter].width = min(
                max(max_width + 2, 12), 45
            )


def highlight_summary_sheet(writer):
    """「検査結果」シートの総合判定を目立たせ、結果列の寄せをそろえる。"""
    worksheet = writer.book["検査結果"]

    for row in worksheet.iter_rows(min_row=2):
        label_cell, value_cell = row[0], row[1]
        # 数字と文字が混ざっていても、結果列の寄せをそろえる。
        value_cell.alignment = Alignment(horizontal="left")

        if label_cell.value == "総合判定":
            style = STATUS_STYLES.get(value_cell.value)
            if style:
                value_cell.fill = PatternFill("solid", fgColor=style["fill"])
                value_cell.font = Font(color=style["font"], bold=True)


def main(argv=None):
    # argv を渡さない(テストなど)ときは、指定なしとして動く。
    args = parse_args([] if argv is None else argv)
    input_file = Path(args.input_file)
    output_file = Path(args.output)

    if not input_file.exists():
        print(f"エラー：{input_file} が見つかりません。")
        return 1

    # 入力のCSVを、Excelで上書きしてしまわないようにする。
    if is_same_file(input_file, output_file):
        print(
            "エラー：保存先が、検査するCSVと同じです。"
            "元のファイルを書き換えないように、別の名前を指定してください。"
        )
        return 1

    rules = None
    if args.config:
        try:
            rules = load_rules(args.config)
        except RulesError as error:
            print(f"エラー：{error}")
            return 1

    try:
        data = read_csv_safely(input_file)
        # 重複・欠損の判定は、CSVに書かれた文字のまま行う(007と7を同じ値にしない)。
        text = read_csv_safely(input_file, dtype=str)
    except pd.errors.EmptyDataError:
        print(f"エラー：{input_file} にデータがありません。")
        return 1
    except (pd.errors.ParserError, ValueError) as error:
        print(f"エラー：{input_file} を読み込めませんでした。({str(error).strip()})")
        return 1

    data = restore_leading_zeros(data, text)

    row_count = len(data)
    column_count = len(data.columns)
    missing_count = int(text.isna().sum().sum())
    duplicate_count = int(text.duplicated().sum())

    if rules is None:
        missing_mask = text.isna().any(axis=1)
        duplicate_mask = text.duplicated(keep=False)
        rule_results = None
        status = (
            "問題あり"
            if missing_count > 0 or duplicate_count > 0
            else "問題なし"
        )
    else:
        # 設定ファイルがあるときは、ルールに違反したかどうかで判定する。
        evaluation = evaluate_rules(text, rules)
        missing_mask = evaluation["missing_rows"]
        duplicate_mask = evaluation["duplicate_rows"]
        rule_results = evaluation["results"]
        status = "問題あり" if evaluation["violations"] > 0 else "問題なし"

    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    items = ["検査したCSV", "検査日時", "データ件数", "列数", "欠損セル数", "重複件数"]
    values = [str(input_file), checked_at, row_count, column_count, missing_count, duplicate_count]
    if rule_results is not None:
        items += ["検査ルール(設定ファイル)", "ルール違反数"]
        values += [str(args.config), evaluation["violations"]]
    items.append("総合判定")
    values.append(status)
    summary = pd.DataFrame({"確認項目": items, "結果": values})

    column_info = pd.DataFrame(
        {
            "列名": data.columns,
            "データ型": [str(data[column].dtype) for column in data.columns],
            "有効データ数": [int(text[column].notna().sum()) for column in data.columns],
            "欠損数": [int(text[column].isna().sum()) for column in data.columns],
            "ユニーク数": [int(text[column].nunique(dropna=True)) for column in data.columns],
        }
    )

    missing_rows = data[missing_mask]
    duplicate_rows = data[duplicate_mask]

    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="検査結果", index=False)
        if rule_results is not None:
            rule_table = pd.DataFrame(
                {
                    "ルール": [r["rule"] for r in rule_results],
                    "設定": [r["setting"] for r in rule_results],
                    "結果": ["OK" if r["ok"] else "NG" for r in rule_results],
                    "内容": [r["detail"] for r in rule_results],
                }
            )
            rule_table.to_excel(writer, sheet_name="ルール判定", index=False)
        column_info.to_excel(writer, sheet_name="列情報", index=False)
        missing_rows.to_excel(writer, sheet_name="欠損行", index=False)
        duplicate_rows.to_excel(writer, sheet_name="重複行", index=False)
        data.to_excel(writer, sheet_name="元データ", index=False)

        format_workbook(writer)
        highlight_summary_sheet(writer)

    print(f"完了：{output_file} を作成しました。")
    if rule_results is not None:
        for r in rule_results:
            print(f"ルール {'OK' if r['ok'] else 'NG'}：{r['rule']}({r['setting']}) {r['detail']}")
    print(
        f"データ件数={row_count} / "
        f"欠損セル数={missing_count} / "
        f"重複件数={duplicate_count} / "
        f"判定={status}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
