import argparse
import os
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill

from csv_history import HistoryError, format_history, load_history, open_history, record_inspection
from csv_rules import RulesError, evaluate_rules, load_rules


DEFAULT_INPUT_FILE = "sample.csv"
DEFAULT_OUTPUT_FILE = "report.xlsx"
DEFAULT_OUTPUT_FOLDER = "reports"
SUMMARY_FILE_NAME = "summary.xlsx"

# カンマ区切りとして読んだ結果が1列だけになったとき、
# 見出しにこれらの文字が含まれていれば、その文字を区切り文字として読み直す。
CANDIDATE_DELIMITERS = ["\t", ";", "|"]
# 先頭に0がある数字(007、0123など)。IDや郵便番号の先頭の0を守るために使う。
LEADING_ZERO_PATTERN = r"^[+-]?0\d"

# 総合判定のセルを目立たせる色(薄い塗りつぶし・濃い文字色)。
STATUS_STYLES = {
    "問題あり": {"fill": "FFC7CE", "font": "9C0006"},
    "問題なし": {"fill": "C6EFCE", "font": "006100"},
    "エラー": {"fill": "FFEB9C", "font": "9C5700"},
}


def parse_args(argv):
    """コマンドで指定された、検査するCSVと出力先を読み取る。"""
    parser = argparse.ArgumentParser(
        description="CSVファイルを検査して、結果をExcelレポートにまとめます。"
    )
    parser.add_argument(
        "input_file",
        nargs="?",
        default=None,
        help=f"検査するCSVファイル(省略すると {DEFAULT_INPUT_FILE})",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help=(
            f"作成するExcelファイル(省略すると {DEFAULT_OUTPUT_FILE})。"
            f"--folder のときは、結果を入れるフォルダ(省略すると {DEFAULT_OUTPUT_FOLDER})"
        ),
    )
    parser.add_argument(
        "-c",
        "--config",
        default=None,
        help="検査ルールを書いたJSONファイル(省略すると、すべての列を対象に検査します)",
    )
    parser.add_argument(
        "-f",
        "--folder",
        default=None,
        help="このフォルダの中の .csv をまとめて検査します(サブフォルダは対象外)",
    )
    parser.add_argument(
        "--history",
        default=None,
        metavar="DB",
        help="検査結果をこのSQLiteファイルに記録します(なければ作ります。検査のたびに追記)",
    )
    parser.add_argument(
        "--show-history",
        default=None,
        metavar="DB",
        help="記録された検査結果を、前回との違いつきで表示します(検査はしません)",
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


def inspect_csv(input_file, output_file, rules=None, config_path=None):
    """1つのCSVを検査して、Excelレポートを作る。画面には何も表示しない。

    戻り値は辞書。うまくいかなかったときは "error" にメッセージが入り、Excelは作られない。
    成功したときは、件数・判定・ルール結果などが入る。
    """
    if not input_file.exists():
        return {"error": f"{input_file} が見つかりません。"}

    # 入力のCSVを、Excelで上書きしてしまわないようにする。
    if is_same_file(input_file, output_file):
        return {
            "error": "保存先が、検査するCSVと同じです。"
            "元のファイルを書き換えないように、別の名前を指定してください。"
        }

    try:
        data = read_csv_safely(input_file)
        # 重複・欠損の判定は、CSVに書かれた文字のまま行う(007と7を同じ値にしない)。
        text = read_csv_safely(input_file, dtype=str)
    except pd.errors.EmptyDataError:
        return {"error": f"{input_file} にデータがありません。"}
    except (pd.errors.ParserError, ValueError) as error:
        return {"error": f"{input_file} を読み込めませんでした。({str(error).strip()})"}

    # データの行が見出しより多くの列を持つと、pandasは先頭の列を行番号として読んでしまう。
    # 黙って列がずれたまま検査しないよう、壊れたCSVとして扱う。
    if not isinstance(data.index, pd.RangeIndex) or not isinstance(text.index, pd.RangeIndex):
        return {
            "error": f"{input_file} を読み込めませんでした。"
            "(データの行に、見出しより多くの列があります)"
        }

    data = restore_leading_zeros(data, text)

    row_count = len(data)
    column_count = len(data.columns)
    missing_count = int(text.isna().sum().sum())
    duplicate_count = int(text.duplicated().sum())

    if rules is None:
        missing_mask = text.isna().any(axis=1)
        duplicate_mask = text.duplicated(keep=False)
        rule_results = None
        violations = None
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
        violations = evaluation["violations"]
        status = "問題あり" if violations > 0 else "問題なし"

    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    items = ["検査したCSV", "検査日時", "データ件数", "列数", "欠損セル数", "重複件数"]
    values = [str(input_file), checked_at, row_count, column_count, missing_count, duplicate_count]
    if rule_results is not None:
        items += ["検査ルール(設定ファイル)", "ルール違反数"]
        values += [str(config_path), violations]
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

    return {
        "error": None,
        "checked_at": checked_at,
        "rows": row_count,
        "columns": column_count,
        "missing": missing_count,
        "duplicates": duplicate_count,
        "violations": violations,
        "status": status,
        "rule_results": rule_results,
    }


def find_csv_files(folder):
    """フォルダ直下の .csv(大文字小文字は問わない)を、名前順に返す。"""
    return sorted(
        (path for path in folder.iterdir() if path.is_file() and path.suffix.lower() == ".csv"),
        key=lambda path: path.name.lower(),
    )


def unique_report_name(csv_file, used):
    """CSVごとのExcelの名前(<CSV名>_report.xlsx)。同じ名前になるときは番号を付ける。"""
    base = f"{csv_file.stem}_report"
    name = f"{base}.xlsx"
    number = 2
    while name.lower() in used:
        name = f"{base}_{number}.xlsx"
        number += 1
    used.add(name.lower())
    return name


def write_folder_summary(output_folder, folder, rows, rules_path, has_rules):
    """全CSVの判定を1枚にまとめた summary.xlsx を作る。"""
    path = output_folder / SUMMARY_FILE_NAME
    counts = {
        status: sum(1 for row in rows if row["判定"] == status)
        for status in ("問題なし", "問題あり", "エラー")
    }
    overall = pd.DataFrame(
        {
            "確認項目": [
                "検査したフォルダ",
                "検査日時",
                "CSVの数",
                "問題なし",
                "問題あり",
                "エラー(検査できなかった)",
                "検査ルール(設定ファイル)",
            ],
            "結果": [
                str(folder),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                len(rows),
                counts["問題なし"],
                counts["問題あり"],
                counts["エラー"],
                str(rules_path) if rules_path else "(なし)",
            ],
        }
    )
    columns = ["ファイル名", "判定", "データ件数", "列数", "欠損セル数", "重複件数"]
    if has_rules:
        columns.append("ルール違反数")
    columns += ["レポート", "内容"]
    table = pd.DataFrame(rows, columns=columns)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        overall.to_excel(writer, sheet_name="全体結果", index=False)
        table.to_excel(writer, sheet_name="一覧", index=False)
        format_workbook(writer)

        sheet = writer.book["一覧"]
        status_column = columns.index("判定") + 1
        for row in sheet.iter_rows(min_row=2):
            cell = row[status_column - 1]
            style = STATUS_STYLES.get(cell.value)
            if style:
                cell.fill = PatternFill("solid", fgColor=style["fill"])
                cell.font = Font(color=style["font"], bold=True)
    return path


def run_folder(args, rules, history=None):
    """フォルダの中のCSVをまとめて検査する。CSVごとのExcelと、一覧(summary.xlsx)を作る。"""
    if args.input_file:
        print("エラー：--folder と、CSVファイルの指定は同時に使えません。")
        return 1

    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"エラー：フォルダ {folder} が見つかりません。")
        return 1

    csv_files = find_csv_files(folder)
    if not csv_files:
        print(f"エラー：フォルダ {folder} に .csv ファイルがありません。")
        return 1

    output_folder = Path(args.output or DEFAULT_OUTPUT_FOLDER)
    try:
        output_folder.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        print(f"エラー：結果を入れるフォルダ {output_folder} を作れませんでした。({error})")
        return 1

    rows = []
    used_names = {SUMMARY_FILE_NAME.lower()}
    for csv_file in csv_files:
        report_name = unique_report_name(csv_file, used_names)
        result = inspect_csv(csv_file, output_folder / report_name, rules, args.config)
        if history is not None:
            try:
                record_inspection(history, csv_file, result, args.config)
            except HistoryError as error:
                print(f"エラー：{error}")
                return 1
        row = {"ファイル名": csv_file.name}
        if result["error"]:
            row.update({"判定": "エラー", "レポート": "", "内容": result["error"]})
            print(f"エラー  {csv_file.name}：{result['error']}")
        else:
            row.update(
                {
                    "判定": result["status"],
                    "データ件数": result["rows"],
                    "列数": result["columns"],
                    "欠損セル数": result["missing"],
                    "重複件数": result["duplicates"],
                    "ルール違反数": result["violations"],
                    "レポート": report_name,
                    "内容": "",
                }
            )
            print(
                f"{result['status']}  {csv_file.name}"
                f"(データ件数={result['rows']} / 欠損セル数={result['missing']} / 重複件数={result['duplicates']})"
            )
        rows.append(row)

    summary_path = write_folder_summary(output_folder, folder, rows, args.config, rules is not None)
    counts = {s: sum(1 for r in rows if r["判定"] == s) for s in ("問題なし", "問題あり", "エラー")}
    print(
        f"完了：{len(rows)}件を検査しました(問題なし={counts['問題なし']} / "
        f"問題あり={counts['問題あり']} / エラー={counts['エラー']})。"
    )
    print(f"一覧：{summary_path}")
    if history is not None:
        print(f"記録：{args.history} に追記しました。")
    return 1 if counts["エラー"] else 0


def main(argv=None):
    # argv を渡さない(テストなど)ときは、指定なしとして動く。
    args = parse_args([] if argv is None else argv)

    rules = None
    if args.config:
        try:
            rules = load_rules(args.config)
        except RulesError as error:
            print(f"エラー：{error}")
            return 1

    if args.show_history:
        return show_history(args)

    history = None
    if args.history:
        try:
            history = open_history(args.history)
        except HistoryError as error:
            print(f"エラー：{error}")
            return 1

    try:
        return run_inspection(args, rules, history)
    finally:
        if history is not None:
            history.close()


def show_history(args):
    """--show-history:記録を表示するだけ。検査はしない。"""
    if args.input_file or args.folder or args.history or args.config:
        print("エラー：--show-history は、検査の指定(CSV・--folder・--history・--config)と同時に使えません。")
        return 1
    try:
        records = load_history(args.show_history)
    except HistoryError as error:
        print(f"エラー：{error}")
        return 1
    if not records:
        print("記録がありません。")
        return 0
    for line in format_history(records):
        print(line)
    print(f"合計 {len(records)} 件の記録")
    return 0


def run_inspection(args, rules, history):
    if args.folder:
        return run_folder(args, rules, history)

    input_file = Path(args.input_file or DEFAULT_INPUT_FILE)
    output_file = Path(args.output or DEFAULT_OUTPUT_FILE)

    result = inspect_csv(input_file, output_file, rules, args.config)
    if history is not None:
        try:
            record_inspection(history, input_file, result, args.config)
        except HistoryError as error:
            print(f"エラー：{error}")
            return 1
    if result["error"]:
        print(f"エラー：{result['error']}")
        return 1

    print(f"完了：{output_file} を作成しました。")
    if result["rule_results"] is not None:
        for r in result["rule_results"]:
            print(f"ルール {'OK' if r['ok'] else 'NG'}：{r['rule']}({r['setting']}) {r['detail']}")
    print(
        f"データ件数={result['rows']} / "
        f"欠損セル数={result['missing']} / "
        f"重複件数={result['duplicates']} / "
        f"判定={result['status']}"
    )
    if history is not None:
        print(f"記録：{args.history} に追記しました。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
