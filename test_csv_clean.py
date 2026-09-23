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
