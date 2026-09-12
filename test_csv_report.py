import pandas as pd
from openpyxl import load_workbook

from csv_report import read_csv_safely, main


def test_read_csv_utf8(tmp_path):
    csv_file = tmp_path / "utf8.csv"
    csv_file.write_text(
        "id,name\n1,Aoki\n2,Sato\n",
        encoding="utf-8-sig",
    )

    data = read_csv_safely(csv_file)

    assert len(data) == 2
    assert list(data.columns) == ["id", "name"]


def test_read_csv_cp932(tmp_path):
    csv_file = tmp_path / "cp932.csv"
    csv_file.write_text(
        "id,name\n1,青木\n2,佐藤\n",
        encoding="cp932",
    )

    data = read_csv_safely(csv_file)

    assert len(data) == 2
    assert data.loc[0, "name"] == "青木"


def test_report_generation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    sample = pd.DataFrame(
        {
            "employee_id": [1001, 1002, 1003, 1002, 1004],
            "name": ["Aoki", "Sato", "Tanaka", "Sato", "Suzuki"],
            "department": ["Care", "Office", None, "Office", "Care"],
            "hours_worked": [8, 7.5, 8, 7.5, None],
        }
    )
    sample.to_csv("sample.csv", index=False, encoding="utf-8-sig")

    main()

    report_file = tmp_path / "report.xlsx"
    assert report_file.exists()

    workbook = load_workbook(report_file, data_only=True)

    assert workbook.sheetnames == [
        "検査結果",
        "列情報",
        "欠損行",
        "重複行",
        "元データ",
    ]

    sheet = workbook["検査結果"]

    assert sheet["B2"].value == 5
    assert sheet["B3"].value == 4
    assert sheet["B4"].value == 2
    assert sheet["B5"].value == 1
    assert sheet["B6"].value == "問題あり"