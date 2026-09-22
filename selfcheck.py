"""Быстрая проверка чистых функций скрипта на синтетических данных."""

from pathlib import Path

from reset_status import (
    Config,
    build_updates,
    cell_link,
    column_letter,
    extract_spreadsheet_id,
    find_status_column,
)

config = Config(
    spreadsheet_id="sheet-id",
    index_sheet="Чеклисты",
    credentials_path=Path("credentials.json"),
    status_headers=["Статус", "Чеклист", "Status"],
    reset_from=["pass", "fail"],
    reset_to="test",
)

assert column_letter(0) == "A"
assert column_letter(25) == "Z"
assert column_letter(26) == "AA"
assert column_letter(27) == "AB"

assert (
    extract_spreadsheet_id("https://docs.google.com/spreadsheets/d/ABC123/edit#gid=7")
    == "ABC123"
)
assert extract_spreadsheet_id("ABC123") == "ABC123"

assert cell_link({"hyperlink": "http://a"}) == "http://a"
assert cell_link({"textFormatRuns": [{"format": {"link": {"uri": "http://b"}}}]}) == "http://b"
assert cell_link({"userEnteredValue": {"formulaValue": '=HYPERLINK("http://c";"Имя")'}}) == "http://c"
assert cell_link({"formattedValue": "Просто текст"}) is None

grid = [
    ["Название", "Чеклист", "Комментарий"],
    ["Экраны подписки", "pass", ""],
    ["Интерфейс", "PASS ", "ок"],
    ["Реклама", "test", ""],
    ["Appsflyer", "fail", ""],
    ["Аналитика", "", ""],
    ["Обновления", "pass", ""],
]

assert find_status_column(grid, config.status_headers) == (0, 1)

updates = build_updates("Чеклисты", grid, config)
ranges = [update["range"] for update in updates]
assert ranges == ["'Чеклисты'!B2:B3", "'Чеклисты'!B5:B5", "'Чеклисты'!B7:B7"], ranges
assert [len(update["values"]) for update in updates] == [2, 1, 1]
assert updates[0]["values"] == [["test"], ["test"]]

no_header = build_updates("Пустая", [["Что-то"], ["pass"]], config)
assert no_header == []

ragged = build_updates("Рваная", [["Название", "Статус"], ["Пуши"], ["Оффер", "fail"]], config)
assert [update["range"] for update in ragged] == ["'Рваная'!B3:B3"]

quoted = build_updates("O'Brien", grid, config)
assert quoted[0]["range"].startswith("'O''Brien'!B")

print("selfcheck ok")
