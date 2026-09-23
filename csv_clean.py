import argparse
import sys
from pathlib import Path

import pandas as pd


DEFAULT_OUTPUT_FILE = "cleaned.csv"


def parse_args(argv):
    """コマンドで指定された、整形するCSVと出力先を読み取る。"""
    parser = argparse.ArgumentParser(
        description=(
            "CSVファイルを整形して、別のCSVファイルとして保存します。"
            "元のファイルは書き換えません。"
        )
    )
    parser.add_argument(
        "input_file",
        help="整形するCSVファイル",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=DEFAULT_OUTPUT_FILE,
        help=f"整形結果を保存するCSVファイル(省略すると {DEFAULT_OUTPUT_FILE})",
    )
    return parser.parse_args(argv)


def read_csv_as_text(file_path):
    """CSVを、すべて文字のまま読み込む。

    数字として読むと「007」が「7」に変わってしまうため、
    整形では見た目のまま扱う。空欄も空欄のまま残す。
    UTF-8とWindows用の文字コードに対応する。
    """
    for encoding in ("utf-8-sig", "cp932"):
        try:
            return pd.read_csv(
                file_path,
                encoding=encoding,
                dtype=str,
                keep_default_na=False,
            )
        except UnicodeDecodeError:
            continue

    raise ValueError("CSVの文字コードを判定できませんでした。")


def trim_spaces(data):
    """見出しとセルの前後の空白(全角の空白を含む)を消す。

    整形後のデータと、空白を消した箇所の数を返す。
    """
    trimmed = data.apply(lambda column: column.str.strip())
    changed_cells = int((trimmed != data).sum().sum())

    trimmed_names = [name.strip() for name in data.columns]
    changed_names = sum(
        1 for before, after in zip(data.columns, trimmed_names) if before != after
    )
    trimmed.columns = trimmed_names

    return trimmed, changed_cells + changed_names


def remove_duplicate_rows(data):
    """完全に同じ内容の行を、最初の1行だけ残して取り除く。

    整形後のデータと、取り除いた行数を返す。
    """
    unique_data = data.drop_duplicates()
    return unique_data, len(data) - len(unique_data)


def main(argv=None):
    args = parse_args(argv)
    input_file = Path(args.input_file)
    output_file = Path(args.output)

    if not input_file.exists():
        print(f"エラー：{input_file} が見つかりません。")
        return 1

    if input_file.resolve() == output_file.resolve():
        print(
            "エラー：保存先が、整形するCSVと同じです。"
            "元のファイルを書き換えないように、別の名前を指定してください。"
        )
        return 1

    try:
        data = read_csv_as_text(input_file)
    except pd.errors.EmptyDataError:
        print(f"エラー：{input_file} にデータがありません。")
        return 1
    except ValueError as error:
        print(f"エラー：{input_file} を読み込めませんでした。({error})")
        return 1

    row_count = len(data)

    data, space_count = trim_spaces(data)
    data, duplicate_count = remove_duplicate_rows(data)

    try:
        data.to_csv(output_file, index=False, encoding="utf-8-sig")
    except OSError:
        print(
            f"エラー：{output_file} に保存できませんでした。"
            "Excelなどで開いていないか、保存先のフォルダがあるか確認してください。"
        )
        return 1

    print(f"完了：{output_file} を作成しました。")
    print(
        f"データ件数={row_count}→{len(data)} / "
        f"空白を消した箇所={space_count} / "
        f"取り除いた重複行={duplicate_count}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
