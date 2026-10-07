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


# ---- 並べ替え(--sort・--desc)と列名の変更(--rename) ----

def run_clean(tmp_path, text, *options):
    input_file = write_csv(tmp_path / "input.csv", text)
    output_file = tmp_path / "output.csv"
    result = main([str(input_file), "-o", str(output_file), *options])
    return result, output_file


def test_sort_numeric_column_by_size_not_by_text(tmp_path):
    # 文字の順だと「100」が「30」より先に来てしまうので、数の大きさで並べる。
    result, out = run_clean(tmp_path, "id,amount\n1,100\n2,30\n3,50\n", "--sort", "amount")
    assert result == 0
    assert list(read_output(out)["amount"]) == ["30", "50", "100"]


def test_sort_descending(tmp_path):
    result, out = run_clean(tmp_path, "id,amount\n1,100\n2,30\n3,50\n", "--sort", "amount", "--desc")
    assert result == 0
    assert list(read_output(out)["amount"]) == ["100", "50", "30"]


def test_sort_keeps_leading_zeros_in_values(tmp_path):
    # 並べ替えでも、「007」は「007」のまま。
    result, out = run_clean(tmp_path, "id,n\n007,2\n003,1\n", "--sort", "n")
    assert result == 0
    assert list(read_output(out)["id"]) == ["003", "007"]


def test_sort_text_column_uses_text_order(tmp_path):
    result, out = run_clean(tmp_path, "id,name\n1,Sato\n2,Aoki\n3,Tanaka\n", "--sort", "name")
    assert result == 0
    assert list(read_output(out)["name"]) == ["Aoki", "Sato", "Tanaka"]


def test_sort_puts_blank_values_last_in_both_directions(tmp_path):
    text = "id,amount\n1,\n2,30\n3,100\n"
    _, up = run_clean(tmp_path, text, "--sort", "amount")
    assert list(read_output(up)["id"]) == ["2", "3", "1"]
    _, down = run_clean(tmp_path, text, "--sort", "amount", "--desc")
    assert list(read_output(down)["id"]) == ["3", "2", "1"]


def test_sort_keeps_original_order_for_equal_values(tmp_path):
    text = "id,group\nA,2\nB,1\nC,2\nD,1\n"
    _, up = run_clean(tmp_path, text, "--sort", "group")
    assert list(read_output(up)["id"]) == ["B", "D", "A", "C"]
    _, down = run_clean(tmp_path, text, "--sort", "group", "--desc")
    assert list(read_output(down)["id"]) == ["A", "C", "B", "D"]


def test_sort_mixed_numbers_and_text_falls_back_to_text_order(tmp_path):
    result, out = run_clean(tmp_path, "id,v\n1,10\n2,9\n3,abc\n", "--sort", "v")
    assert result == 0
    assert list(read_output(out)["v"]) == ["10", "9", "abc"]


def test_sort_unknown_column_is_an_error_and_no_file(tmp_path, capsys):
    result, out = run_clean(tmp_path, "id,amount\n1,100\n", "--sort", "price")
    assert result == 1
    assert not out.exists()
    assert "並べ替えに使う列名「price」がCSVに見つかりません" in capsys.readouterr().out


def test_desc_without_sort_is_an_error(tmp_path, capsys):
    result, out = run_clean(tmp_path, "id,amount\n1,100\n", "--desc")
    assert result == 1
    assert not out.exists()
    assert "--desc は --sort と一緒に" in capsys.readouterr().out


def test_rename_changes_only_the_header(tmp_path, capsys):
    result, out = run_clean(tmp_path, "id,name,dept\n007,Aoki,Care\n", "--rename", "name=氏名,dept=所属")
    assert result == 0
    data = read_output(out)
    assert list(data.columns) == ["id", "氏名", "所属"]
    assert data.to_dict("records") == [{"id": "007", "氏名": "Aoki", "所属": "Care"}]
    assert "列名の変更=name→氏名、dept→所属" in capsys.readouterr().out


def test_rename_unknown_column_is_an_error_and_no_file(tmp_path, capsys):
    result, out = run_clean(tmp_path, "id,name\n1,Aoki\n", "--rename", "title=氏名")
    assert result == 1
    assert not out.exists()
    assert "名前を変える列がCSVに見つかりません：title" in capsys.readouterr().out


def test_rename_to_an_existing_column_name_is_an_error(tmp_path, capsys):
    result, out = run_clean(tmp_path, "id,name\n1,Aoki\n", "--rename", "name=id")
    assert result == 1
    assert not out.exists()
    assert "ほかの列と重なります" in capsys.readouterr().out


def test_rename_two_columns_to_the_same_name_is_an_error(tmp_path):
    result, out = run_clean(tmp_path, "a,b\n1,2\n", "--rename", "a=x,b=x")
    assert result == 1
    assert not out.exists()


def test_rename_same_column_twice_is_an_error(tmp_path):
    result, out = run_clean(tmp_path, "a,b\n1,2\n", "--rename", "a=x,a=y")
    assert result == 1
    assert not out.exists()


def test_rename_swapping_two_names_is_allowed(tmp_path):
    # 入れ替えは、重なりにならない。
    result, out = run_clean(tmp_path, "a,b\n1,2\n", "--rename", "a=b,b=a")
    assert result == 0
    assert read_output(out).to_dict("records") == [{"b": "1", "a": "2"}]


def test_rename_bad_format_is_an_error(tmp_path, capsys):
    for bad in ["name", "name=", "=氏名", ","]:
        result, out = run_clean(tmp_path, "id,name\n1,Aoki\n", "--rename", bad)
        assert result == 1
        assert not out.exists()
    assert "--rename の指定" in capsys.readouterr().out


def test_where_drop_sort_use_original_names_and_rename_is_applied_last(tmp_path):
    text = "id,dept,amount\n1,Care,50\n2,Office,10\n3,Care,100\n"
    result, out = run_clean(
        tmp_path, text,
        "--where", "dept=Care", "--sort", "amount", "--desc",
        "--drop", "dept", "--rename", "amount=金額",
    )
    assert result == 0
    assert read_output(out).to_dict("records") == [
        {"id": "3", "金額": "100"},
        {"id": "1", "金額": "50"},
    ]


def test_rename_a_dropped_column_is_an_error(tmp_path):
    result, out = run_clean(tmp_path, "id,dept\n1,Care\n", "--drop", "dept", "--rename", "dept=所属")
    assert result == 1
    assert not out.exists()


def test_sort_and_rename_do_not_change_the_input_file(tmp_path):
    text = "id,amount\n1,100\n2,30\n"
    input_file = write_csv(tmp_path / "input.csv", text)
    before = input_file.read_bytes()
    main([str(input_file), "-o", str(tmp_path / "o.csv"), "--sort", "amount", "--rename", "amount=金額"])
    assert input_file.read_bytes() == before
