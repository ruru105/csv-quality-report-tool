"""CSVチェッカーの検査ルール(設定ファイル)を読み込み、判定する。

設定ファイルはJSONで、次の3つの項目だけを書ける(すべて省略可)。

    {
      "required_columns": ["employee_id", "name"],
      "not_null_columns": ["employee_id", "name"],
      "unique_columns": ["employee_id"]
    }

- required_columns : CSVになければ「問題あり」にする列
- not_null_columns : 空欄(欠損)があれば「問題あり」にする列。省略すると、すべての列が対象
- unique_columns   : この列の組み合わせが同じ行を重複とみなす列。省略すると、行全体が同じものが重複
"""

import json
from pathlib import Path

import pandas as pd

ALLOWED_KEYS = ("required_columns", "not_null_columns", "unique_columns")


class RulesError(Exception):
    """設定ファイルが読めない、または書き方が正しくないときのエラー。"""


def load_rules(path):
    """設定ファイルを読み込み、検査できる形にして返す。書き方が違えばRulesErrorにする。"""
    path = Path(path)
    if not path.exists():
        raise RulesError(f"設定ファイル {path} が見つかりません。")

    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except UnicodeDecodeError:
        raise RulesError(f"設定ファイル {path} の文字コードを読めません。UTF-8で保存してください。")
    except json.JSONDecodeError as error:
        raise RulesError(f"設定ファイル {path} がJSONとして読めません。({error})")

    if not isinstance(raw, dict):
        raise RulesError("設定ファイルは { ... } の形で書いてください。")

    unknown = [key for key in raw if key not in ALLOWED_KEYS]
    if unknown:
        raise RulesError(
            f"設定ファイルに未対応の項目があります: {', '.join(unknown)}"
            f"(使える項目: {', '.join(ALLOWED_KEYS)})"
        )

    rules = {"required_columns": [], "not_null_columns": None, "unique_columns": None}
    for key, value in raw.items():
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(item, str) and item.strip() for item in value)
        ):
            raise RulesError(
                f"設定ファイルの {key} は、列名の文字列を1つ以上並べた [ ... ] で書いてください。"
                "(すべての列を対象にしたいときは、この項目ごと書かないでください)"
            )
        rules[key] = list(dict.fromkeys(value))
    return rules


def _names(columns):
    return "、".join(columns)


def evaluate_rules(text, rules):
    """ルールに照らして検査する。

    text は、CSVに書かれた文字のまま読み込んだ表(dtype=str)。
    戻り値:
        results      ルールごとの結果(rule・setting・ok・detail)の一覧
        missing_rows 欠損の判定対象の列に空欄がある行(True/False)
        duplicate_rows 重複の判定対象の列が同じ行(True/False。最初の行も含む)
        violations   違反したルールの数
    """
    present = set(text.columns)
    results = []

    # 1. 必須列
    required = rules["required_columns"]
    if required:
        absent = [column for column in required if column not in present]
        results.append(
            {
                "rule": "必須列",
                "setting": _names(required),
                "ok": not absent,
                "detail": "すべてあります" if not absent else f"ない列: {_names(absent)}",
            }
        )

    # 2. 欠損を許さない列
    not_null = rules["not_null_columns"]
    targets = list(text.columns) if not_null is None else not_null
    absent = [column for column in targets if column not in present]
    checked = [column for column in targets if column in present]
    empty_cells = text[checked].isna() if checked else text.iloc[:, :0].isna()
    missing_rows = empty_cells.any(axis=1) if checked else pd.Series(False, index=text.index)
    per_column = {column: int(empty_cells[column].sum()) for column in checked}
    total_missing = sum(per_column.values())
    details = []
    if total_missing:
        details.append(
            f"欠損セル {total_missing}個("
            + "、".join(f"{column}={count}" for column, count in per_column.items() if count)
            + ")"
        )
    if absent:
        details.append(f"CSVにない列: {_names(absent)}")
    results.append(
        {
            "rule": "欠損を許さない列",
            "setting": "すべての列" if not_null is None else _names(not_null),
            "ok": not details,
            "detail": "欠損はありません" if not details else " / ".join(details),
        }
    )

    # 3. 重複を判定する列
    unique = rules["unique_columns"]
    keys = list(text.columns) if unique is None else unique
    absent = [column for column in keys if column not in present]
    key_columns = [column for column in keys if column in present]
    if key_columns:
        duplicate_rows = text.duplicated(subset=key_columns, keep=False)
        duplicate_count = int(text.duplicated(subset=key_columns).sum())
    else:
        duplicate_rows = pd.Series(False, index=text.index)
        duplicate_count = 0
    details = []
    if duplicate_count:
        details.append(f"重複件数 {duplicate_count}(重複している行は{int(duplicate_rows.sum())}行)")
    if absent:
        details.append(f"CSVにない列: {_names(absent)}")
    results.append(
        {
            "rule": "重複を判定する列",
            "setting": "すべての列(行全体)" if unique is None else _names(unique),
            "ok": not details,
            "detail": "重複はありません" if not details else " / ".join(details),
        }
    )

    return {
        "results": results,
        "missing_rows": missing_rows,
        "duplicate_rows": duplicate_rows,
        "violations": sum(1 for result in results if not result["ok"]),
    }
