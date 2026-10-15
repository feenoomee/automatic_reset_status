"""Быстрая проверка чистых функций скрипта на синтетических данных."""

from pathlib import Path

import sys
from contextlib import redirect_stdout
from io import StringIO

from reset_status import (
    Config,
    ConfigError,
    ask_spreadsheet,
    build_updates,
    column_letter,
    extract_spreadsheet_id,
    load_config,
)

config = Config(
    spreadsheet_id="sheet-id",
    credentials_path=Path("credentials.json"),
    reset_to="test",
)


def checkbox(checked: bool) -> dict:
    cell: dict = {"dataValidation": {"condition": {"type": "BOOLEAN"}}}
    cell["userEnteredValue"] = {"boolValue": checked}
    if checked:
        cell["formattedValue"] = "TRUE"
    return cell


def custom_checkbox(current: str) -> dict:
    return {
        "dataValidation": {
            "condition": {
                "type": "BOOLEAN",
                "values": [
                    {"userEnteredValue": "yes"},
                    {"userEnteredValue": "no"},
                ],
            }
        },
        "userEnteredValue": {"stringValue": current},
        "formattedValue": current,
    }


def dropdown(value: str, kind: str = "ONE_OF_LIST") -> dict:
    cell: dict = {"dataValidation": {"condition": {"type": kind}}}
    if value:
        cell["userEnteredValue"] = {"stringValue": value}
        cell["formattedValue"] = value
    return cell


assert column_letter(0) == "A"
assert column_letter(25) == "Z"
assert column_letter(26) == "AA"
assert column_letter(27) == "AB"

assert (
    extract_spreadsheet_id("https://docs.google.com/spreadsheets/d/ABC123/edit#gid=7")
    == "ABC123"
)
assert extract_spreadsheet_id("ABC123") == "ABC123"

previous_stdin = sys.stdin
try:
    with redirect_stdout(StringIO()):
        sys.stdin = StringIO("https://docs.google.com/spreadsheets/d/ABC123/edit\n")
        assert ask_spreadsheet() == "https://docs.google.com/spreadsheets/d/ABC123/edit"
        sys.stdin = StringIO("\n")
        assert ask_spreadsheet() == ""
finally:
    sys.stdin = previous_stdin

try:
    load_config(Path("config.example.json"), "")
    raise AssertionError("пустая ссылка должна быть ошибкой")
except ConfigError as error:
    assert "ссылка" in str(error).lower()

grid = [
    [{"formattedValue": "Название"}, {"formattedValue": "Поле"}],
    [{"formattedValue": "Экран"}, checkbox(True)],
    [{"formattedValue": "Интерфейс"}, checkbox(True)],
    [{"formattedValue": "Реклама"}, checkbox(False)],
    [{"formattedValue": "Аналитика"}, dropdown("pass")],
    [{"formattedValue": "Пуши"}, dropdown("test")],
    [{"formattedValue": "Оффер"}, dropdown("FAIL")],
    [{"formattedValue": "Текст"}, {"formattedValue": "pass"}],
    [{"formattedValue": "Пусто"}, dropdown("")],
    [{"formattedValue": "Диапазон"}, dropdown("done", "ONE_OF_RANGE")],
    [{"formattedValue": "Свой чек"}, custom_checkbox("yes")],
    [{"formattedValue": "Свой пустой"}, custom_checkbox("no")],
]

updates, checks, dropdowns = build_updates("Чеклисты", grid, config.reset_to)
ranges = [update["range"] for update in updates]
assert ranges == [
    "'Чеклисты'!B2:B3",
    "'Чеклисты'!B5:B5",
    "'Чеклисты'!B7:B7",
    "'Чеклисты'!B10:B10",
    "'Чеклисты'!B11:B11",
], ranges
assert checks == 3, checks
assert dropdowns == 3, dropdowns
assert updates[0]["values"] == [[False], [False]]
assert updates[1]["values"] == [["test"]]
assert updates[4]["values"] == [["no"]]

plain = build_updates("Пустая", [[{"formattedValue": "pass"}]], config.reset_to)
assert plain[0] == []

localization = [
    [
        {"formattedValue": "Язык"},
        {"formattedValue": "Чек"},
        {"formattedValue": "Комментарий"},
    ],
    [
        {"formattedValue": "Английский"},
        {"formattedValue": "pass", "userEnteredValue": {"stringValue": "pass"}},
        {},
    ],
    [
        {"formattedValue": "Русский"},
        {"formattedValue": "test", "userEnteredValue": {"stringValue": "test"}},
        {},
    ],
    [
        {"formattedValue": "Китайский"},
        {"formattedValue": "fail", "userEnteredValue": {"stringValue": "fail"}},
        {},
    ],
]
table = [{
    "range": {
        "startRowIndex": 0,
        "endRowIndex": 4,
        "startColumnIndex": 0,
        "endColumnIndex": 3,
    },
    "columnProperties": [{
        "columnIndex": 1,
        "columnType": "DROPDOWN",
        "dataValidationRule": {"condition": {"type": "ONE_OF_LIST"}},
    }],
}]
assert build_updates("Локализация", localization, config.reset_to)[0] == []
fixed, table_checks, table_dropdowns = build_updates(
    "Локализация", localization, config.reset_to, table
)
assert [item["range"] for item in fixed] == [
    "'Локализация'!B2:B2",
    "'Локализация'!B4:B4",
], fixed
assert table_checks == 0 and table_dropdowns == 2

shifted = [{
    "range": {"startRowIndex": 0, "endRowIndex": 2, "startColumnIndex": 2},
    "columnProperties": [{"columnIndex": 0, "columnType": "BOOLEAN"}],
}]
checkbox_table, shifted_checks, _ = build_updates(
    "Сдвиг",
    [
        [{}, {}, {"formattedValue": "Чек"}],
        [{}, {}, {"userEnteredValue": {"boolValue": True}}],
    ],
    config.reset_to,
    shifted,
)
assert shifted_checks == 1
assert checkbox_table[0]["range"] == "'Сдвиг'!C2:C2"
assert checkbox_table[0]["values"] == [[False]]

quoted, _, _ = build_updates("O'Brien", grid, config.reset_to)
assert quoted[0]["range"].startswith("'O''Brien'!B")

formula = build_updates(
    "Формула",
    [[
        {
            "dataValidation": {"condition": {"type": "BOOLEAN"}},
            "userEnteredValue": {"formulaValue": "=TRUE"},
        }
    ]],
    config.reset_to,
)
assert formula[0] == []

print("selfcheck ok")
