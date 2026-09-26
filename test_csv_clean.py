import pandas as pd

from csv_clean import main


def write_csv(path, text, encoding="utf-8-sig"):
    path.write_text(text, encoding=encoding)
    return path


def read_output(path):
    """整形後のCSVを、すべて文字のまま読み込む。"""
    return pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)


def test_trim_spaces_and_remove_duplicates(tmp_path, capsys):
    # 前後の空白(全角を含む)を消したあと、同じ内容になった行が取り除かれること。
    input_file = write_csv(
        tmp_path / "input.csv",
        "id,name\n1, Aoki \n2,　Sato\n2,Sato\n1,Aoki\n",
    )
    output_file = tmp_path / "output.csv"

    result = main([str(input_file), "-o", str(output_file)])

    assert result == 0
    assert read_output(output_file).to_dict("records") == [
        {"id": "1", "name": "Aoki"},
        {"id": "2", "name": "Sato"},
    ]

    output = capsys.readouterr().out
    assert "データ件数=4→2" in output
    assert "空白を消した箇所=2" in output
    assert "取り除いた重複行=2" in output


def test_header_spaces_are_removed(tmp_path, capsys):
    input_file = write_csv(tmp_path / "input.csv", " id , name \n1,Aoki\n")
    output_file = tmp_path / "output.csv"

    main([str(input_file), "-o", str(output_file)])

    assert list(read_output(output_file).columns) == ["id", "name"]
    assert "空白を消した箇所=2" in capsys.readouterr().out


def test_original_file_is_not_changed(tmp_path):
    input_file = write_csv(tmp_path / "input.csv", "id,name\n1, Aoki \n1, Aoki \n")
    before = input_file.read_bytes()

    main([str(input_file), "-o", str(tmp_path / "output.csv")])

    assert input_file.read_bytes() == before


def test_values_are_kept_as_written(tmp_path):
    # 先頭の0、空欄、「NA」という文字が、勝手に変わらないこと。
    input_file = write_csv(
        tmp_path / "input.csv",
        "code,name,memo\n007,Aoki,\n008,NA,ok\n",
    )
    output_file = tmp_path / "output.csv"

    main([str(input_file), "-o", str(output_file)])

    assert read_output(output_file).to_dict("records") == [
        {"code": "007", "name": "Aoki", "memo": ""},
        {"code": "008", "name": "NA", "memo": "ok"},
    ]


def test_default_output_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_csv(tmp_path / "input.csv", "id,name\n1,Aoki\n")

    main(["input.csv"])

    assert (tmp_path / "cleaned.csv").exists()


def test_cp932_input_is_saved_as_utf8_with_bom(tmp_path):
    input_file = write_csv(
        tmp_path / "input.csv",
        "id,name\n1,青木\n1,青木\n",
        encoding="cp932",
    )
    output_file = tmp_path / "output.csv"

    main([str(input_file), "-o", str(output_file)])

    assert output_file.read_bytes().startswith(b"\xef\xbb\xbf")
    assert read_output(output_file).to_dict("records") == [
        {"id": "1", "name": "青木"},
    ]


def test_header_only_csv_is_saved_as_header_only(tmp_path):
    input_file = write_csv(tmp_path / "input.csv", "id,name\n")
    output_file = tmp_path / "output.csv"

    result = main([str(input_file), "-o", str(output_file)])

    assert result == 0
    saved = read_output(output_file)
    assert list(saved.columns) == ["id", "name"]
    assert len(saved) == 0


def test_missing_input_file_shows_error(tmp_path, capsys):
    output_file = tmp_path / "output.csv"

    result = main([str(tmp_path / "no_such_file.csv"), "-o", str(output_file)])

    assert result == 1
    assert "見つかりません" in capsys.readouterr().out
    assert not output_file.exists()


def test_same_input_and_output_is_refused(tmp_path, capsys):
    # 元のファイルを上書きしないこと。
    input_file = write_csv(tmp_path / "input.csv", "id,name\n1, Aoki \n")
    before = input_file.read_bytes()

    result = main([str(input_file), "-o", str(input_file)])

    assert result == 1
    assert "元のファイルを書き換えない" in capsys.readouterr().out
    assert input_file.read_bytes() == before


def test_empty_csv_shows_error(tmp_path, capsys):
    input_file = write_csv(tmp_path / "empty.csv", "")
    output_file = tmp_path / "output.csv"

    result = main([str(input_file), "-o", str(output_file)])

    assert result == 1
    assert "データがありません" in capsys.readouterr().out
    assert not output_file.exists()


def test_unwritable_output_shows_error(tmp_path, capsys):
    # 保存先のフォルダがないときに、分かりやすいエラーを出すこと。
    input_file = write_csv(tmp_path / "input.csv", "id,name\n1,Aoki\n")

    result = main([str(input_file), "-o", str(tmp_path / "no_folder" / "output.csv")])

    assert result == 1
    assert "保存できませんでした" in capsys.readouterr().out


def test_where_keeps_only_matching_rows(tmp_path, capsys):
    input_file = write_csv(
        tmp_path / "input.csv",
        "id,department\n1,Care\n2,Office\n3,Care\n",
    )
    output_file = tmp_path / "output.csv"

    result = main(
        [str(input_file), "-o", str(output_file), "--where", "department=Care"]
    )

    assert result == 0
    assert read_output(output_file).to_dict("records") == [
        {"id": "1", "department": "Care"},
        {"id": "3", "department": "Care"},
    ]
    assert "データ件数=3→2" in capsys.readouterr().out


def test_where_is_exact_match_not_partial(tmp_path):
    # 「Care」を指定したとき、「Care部」のような部分一致は含めないこと。
    input_file = write_csv(
        tmp_path / "input.csv",
        "id,department\n1,Care\n2,Care部\n",
    )
    output_file = tmp_path / "output.csv"

    main([str(input_file), "-o", str(output_file), "--where", "department=Care"])

    assert read_output(output_file).to_dict("records") == [
        {"id": "1", "department": "Care"},
    ]


def test_where_no_match_creates_header_only_csv(tmp_path, capsys):
    input_file = write_csv(tmp_path / "input.csv", "id,department\n1,Care\n")
    output_file = tmp_path / "output.csv"

    result = main(
        [str(input_file), "-o", str(output_file), "--where", "department=Office"]
    )

    assert result == 0
    saved = read_output(output_file)
    assert list(saved.columns) == ["id", "department"]
    assert len(saved) == 0
    assert "データ件数=1→0" in capsys.readouterr().out


def test_where_invalid_format_shows_error(tmp_path, capsys):
    input_file = write_csv(tmp_path / "input.csv", "id,department\n1,Care\n")
    output_file = tmp_path / "output.csv"

    result = main(
        [str(input_file), "-o", str(output_file), "--where", "department:Care"]
    )

    assert result == 1
    assert "正しくありません" in capsys.readouterr().out
    assert not output_file.exists()


def test_where_unknown_column_shows_error(tmp_path, capsys):
    input_file = write_csv(tmp_path / "input.csv", "id,department\n1,Care\n")
    output_file = tmp_path / "output.csv"

    result = main(
        [str(input_file), "-o", str(output_file), "--where", "no_such_column=Care"]
    )

    assert result == 1
    assert "見つかりません" in capsys.readouterr().out
    assert not output_file.exists()


def test_drop_single_column(tmp_path, capsys):
    input_file = write_csv(
        tmp_path / "input.csv",
        "id,name,memo\n1,Aoki,内緒\n",
    )
    output_file = tmp_path / "output.csv"

    result = main([str(input_file), "-o", str(output_file), "--drop", "memo"])

    assert result == 0
    assert list(read_output(output_file).columns) == ["id", "name"]
    assert "削除した列=memo" in capsys.readouterr().out


def test_drop_multiple_columns_with_comma(tmp_path):
    input_file = write_csv(
        tmp_path / "input.csv",
        "id,name,memo,note\n1,Aoki,内緒,秘密\n",
    )
    output_file = tmp_path / "output.csv"

    main([str(input_file), "-o", str(output_file), "--drop", "memo,note"])

    assert list(read_output(output_file).columns) == ["id", "name"]


def test_drop_unknown_column_shows_error(tmp_path, capsys):
    input_file = write_csv(tmp_path / "input.csv", "id,name\n1,Aoki\n")
    output_file = tmp_path / "output.csv"

    result = main([str(input_file), "-o", str(output_file), "--drop", "no_such_column"])

    assert result == 1
    assert "見つかりません" in capsys.readouterr().out
    assert not output_file.exists()


def test_drop_all_columns_is_refused(tmp_path, capsys):
    input_file = write_csv(tmp_path / "input.csv", "id,name\n1,Aoki\n")
    output_file = tmp_path / "output.csv"

    result = main([str(input_file), "-o", str(output_file), "--drop", "id,name"])

    assert result == 1
    assert "すべての列を削除することはできません" in capsys.readouterr().out
    assert not output_file.exists()


def test_where_and_drop_together(tmp_path):
    # --where は絞り込みに使った列を、--drop であとから削除できること。
    input_file = write_csv(
        tmp_path / "input.csv",
        "id,department,memo\n1,Care,内緒\n2,Office,内緒\n",
    )
    output_file = tmp_path / "output.csv"

    main(
        [
            str(input_file),
            "-o",
            str(output_file),
            "--where",
            "department=Care",
            "--drop",
            "department,memo",
        ]
    )

    assert read_output(output_file).to_dict("records") == [{"id": "1"}]


def test_tab_separated_input_is_split_into_columns(tmp_path):
    # FX取引ソフトの出力など、タブ区切りのファイルも正しく列を分けて整形できること。
    input_file = write_csv(tmp_path / "input.csv", "id\tname\n1\tAoki\n2\tSato\n")
    output_file = tmp_path / "output.csv"

    result = main([str(input_file), "-o", str(output_file)])

    assert result == 0
    assert read_output(output_file).to_dict("records") == [
        {"id": "1", "name": "Aoki"},
        {"id": "2", "name": "Sato"},
    ]


def test_semicolon_separated_input_is_split_into_columns(tmp_path):
    input_file = write_csv(tmp_path / "input.csv", "id;name\n1;Aoki\n2;Sato\n")
    output_file = tmp_path / "output.csv"

    result = main([str(input_file), "-o", str(output_file)])

    assert result == 0
    assert read_output(output_file).to_dict("records") == [
        {"id": "1", "name": "Aoki"},
        {"id": "2", "name": "Sato"},
    ]


def test_genuinely_single_column_input_stays_single_column(tmp_path):
    # 区切り文字を含まない、もともと1列だけのCSVを誤って分割しないこと。
    input_file = write_csv(tmp_path / "input.csv", "name\nAoki\nSato\n")
    output_file = tmp_path / "output.csv"

    result = main([str(input_file), "-o", str(output_file)])

    assert result == 0
    assert read_output(output_file).to_dict("records") == [
        {"name": "Aoki"},
        {"name": "Sato"},
    ]
