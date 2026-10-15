"""Сброс полей чеклистов Google Sheets.

Скрипт проходит по всем вкладкам таблицы и сбрасывает поля по их типу:
галочку снимает, в выпадающем списке ставит значение из конфига.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_URL_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")

DEFAULTS = {
    "credentials_path": "credentials.json",
    "reset_to": "test",
}
CHECKBOX = "BOOLEAN"
DROPDOWNS = {"ONE_OF_LIST", "ONE_OF_RANGE"}
TABLE_DROPDOWN = "DROPDOWN"
CHECKED_TEXT = {"true", "истина"}


class ConfigError(Exception):
    """Проблема с конфигурацией или доступом."""


@dataclass
class Config:
    spreadsheet_id: str
    credentials_path: Path
    reset_to: str


@dataclass(frozen=True)
class ColumnSpan:
    """Колонка таблицы Google Sheets: чекбокс или выпадающий список."""

    start_row: int
    end_row: int
    kind: str
    condition: dict


def normalize(value: object) -> str:
    return str(value).strip().lower() if value is not None else ""


def extract_spreadsheet_id(raw: str) -> str:
    match = SPREADSHEET_URL_RE.search(raw)
    return match.group(1) if match else raw.strip()


def ask_spreadsheet() -> str:
    """Просит вставить ссылку на таблицу в консоли."""
    try:
        return input("Ссылка на таблицу: ").strip()
    except EOFError:
        return ""


def load_config(config_path: Path, spreadsheet_raw: str) -> Config:
    if not config_path.exists():
        raise ConfigError(
            f"Не найден {config_path}. Скопируй config.example.json в {config_path.name}."
        )

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_raw)
    if not spreadsheet_id:
        raise ConfigError("Нужна ссылка на таблицу.")

    credentials_path = Path(raw.get("credentials_path", DEFAULTS["credentials_path"]))
    if not credentials_path.is_absolute():
        credentials_path = config_path.parent / credentials_path
    if not credentials_path.exists():
        raise ConfigError(
            f"Не найден JSON-ключ service account: {credentials_path}. "
            "См. раздел «Доступ к таблице» в README.md."
        )

    return Config(
        spreadsheet_id=spreadsheet_id,
        credentials_path=credentials_path,
        reset_to=raw.get("reset_to", DEFAULTS["reset_to"]),
    )


def build_service(credentials_path: Path):
    credentials = service_account.Credentials.from_service_account_file(
        str(credentials_path), scopes=SCOPES
    )
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def quote_sheet(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def column_letter(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def fetch_sheet_titles(service, spreadsheet_id: str) -> list[str]:
    """Все вкладки-сетки таблицы по порядку, включая скрытые."""
    response = (
        service.spreadsheets()
        .get(
            spreadsheetId=spreadsheet_id,
            fields="sheets.properties(title,sheetType)",
        )
        .execute()
    )
    return [
        sheet["properties"]["title"]
        for sheet in response.get("sheets", [])
        if sheet["properties"].get("sheetType", "GRID") == "GRID"
    ]


def validation_type(cell: dict | None) -> str | None:
    if not cell:
        return None
    condition = (cell.get("dataValidation") or {}).get("condition") or {}
    return condition.get("type")


def column_spans(tables: Sequence[dict]) -> dict[int, list[ColumnSpan]]:
    """Колонки таблиц, у которых тип поля задан на всю колонку, а не на ячейку."""
    spans: dict[int, list[ColumnSpan]] = {}
    for table in tables:
        grid_range = table.get("range") or {}
        origin_col = grid_range.get("startColumnIndex", 0)
        start_row = grid_range.get("startRowIndex", 0) + 1
        end_row = grid_range.get("endRowIndex", start_row)
        for column in table.get("columnProperties") or []:
            kind = column.get("columnType")
            if kind not in {CHECKBOX, TABLE_DROPDOWN}:
                continue
            sheet_col = origin_col + column.get("columnIndex", 0)
            condition = (column.get("dataValidationRule") or {}).get("condition") or {}
            spans.setdefault(sheet_col, []).append(
                ColumnSpan(start_row, end_row, kind, condition)
            )
    return spans


def span_at(spans: dict[int, list[ColumnSpan]], row: int, col: int) -> ColumnSpan | None:
    for span in spans.get(col, []):
        if span.start_row <= row < span.end_row:
            return span
    return None


def entered_text(cell: dict) -> str:
    entered = cell.get("userEnteredValue") or {}
    if "stringValue" in entered:
        return str(entered["stringValue"]).strip()
    if "numberValue" in entered:
        return str(entered["numberValue"]).strip()
    if "boolValue" in entered:
        return "TRUE" if entered["boolValue"] else "FALSE"
    return str(cell.get("formattedValue") or "").strip()


def planned_reset(
    cell: dict | None, reset_to: str, span: ColumnSpan | None = None
) -> tuple[str, object] | None:
    """Что записать в ячейку, если её поле нужно сбросить.

    Чекбокс со галочкой -> снятая галочка.
    Выпадающий список с выбранным значением -> reset_to.
    Пустые поля и обычный текст не трогаем.
    Тип может быть у самой ячейки или у колонки таблицы.
    """
    if cell is None and span is None:
        return None
    cell = cell or {}
    if "formulaValue" in (cell.get("userEnteredValue") or {}):
        return None

    kind = validation_type(cell)
    condition = (cell.get("dataValidation") or {}).get("condition") or {}
    if kind is None and span is not None:
        kind = "ONE_OF_LIST" if span.kind == TABLE_DROPDOWN else CHECKBOX
        condition = span.condition or condition

    if kind == CHECKBOX:
        custom = condition.get("values") or []
        if len(custom) >= 2:
            checked = str(custom[0].get("userEnteredValue", "")).strip()
            unchecked = custom[1].get("userEnteredValue", "")
            current = entered_text(cell)
            if not current or not checked or normalize(current) != normalize(checked):
                return None
            return "checkbox", unchecked

        entered = cell.get("userEnteredValue") or {}
        if "boolValue" in entered:
            if entered["boolValue"]:
                return "checkbox", False
            return None
        if normalize(cell.get("formattedValue")) in CHECKED_TEXT:
            return "checkbox", False
        return None

    if kind in DROPDOWNS:
        current = entered_text(cell)
        if not current or normalize(current) == normalize(reset_to):
            return None
        return "dropdown", reset_to

    return None


def build_updates(
    sheet_title: str,
    grid: Sequence[Sequence[dict]],
    reset_to: str,
    tables: Sequence[dict] = (),
) -> tuple[list[dict], int, int]:
    """Готовит диапазоны сброса по типу поля в ячейке или колонке таблицы."""
    spans = column_spans(tables)
    width = max((len(row) for row in grid), default=0)
    if spans:
        width = max(width, max(spans) + 1)
    updates: list[dict] = []
    checkbox_cells = 0
    dropdown_cells = 0

    for col in range(width):
        letter = column_letter(col)
        block_start: int | None = None
        block_value: object = None
        block_kind: str | None = None

        def flush(end_row: int) -> None:
            nonlocal block_start, block_value, block_kind, checkbox_cells, dropdown_cells
            if block_start is None or block_kind is None:
                return
            first = block_start + 1
            last = end_row + 1
            count = last - first + 1
            updates.append(
                {
                    "range": f"{quote_sheet(sheet_title)}!{letter}{first}:{letter}{last}",
                    "values": [[block_value] for _ in range(count)],
                }
            )
            if block_kind == "checkbox":
                checkbox_cells += count
            else:
                dropdown_cells += count
            block_start = None
            block_value = None
            block_kind = None

        for row_index, row in enumerate(grid):
            cell = row[col] if col < len(row) else None
            planned = planned_reset(cell, reset_to, span_at(spans, row_index, col))
            if planned is not None and (
                block_start is None or (planned[0] == block_kind and planned[1] == block_value)
            ):
                if block_start is None:
                    block_start = row_index
                    block_kind, block_value = planned
            else:
                flush(row_index - 1)
                if planned is not None:
                    block_start = row_index
                    block_kind, block_value = planned

        flush(len(grid) - 1)

    return updates, checkbox_cells, dropdown_cells


def fetch_grids(
    service, spreadsheet_id: str, titles: Sequence[str]
) -> dict[str, tuple[list[list[dict]], list[dict]]]:
    """Читает ячейки и колонки таблиц: чекбокс или выпадающий список."""
    grids: dict[str, tuple[list[list[dict]], list[dict]]] = {}
    fields = (
        "sheets(properties(title),tables(range,columnProperties("
        "columnIndex,columnType,dataValidationRule)),data(rowData(values("
        "formattedValue,userEnteredValue,dataValidation))))"
    )
    for offset in range(0, len(titles), 5):
        chunk = titles[offset : offset + 5]
        response = (
            service.spreadsheets()
            .get(
                spreadsheetId=spreadsheet_id,
                ranges=[quote_sheet(title) for title in chunk],
                includeGridData=True,
                fields=fields,
            )
            .execute()
        )
        for sheet in response.get("sheets", []):
            title = sheet.get("properties", {}).get("title")
            data = sheet.get("data") or [{}]
            rows = data[0].get("rowData", [])
            grids[title] = (
                [row.get("values", []) for row in rows],
                sheet.get("tables") or [],
            )
    return grids


def run(config: Config) -> int:
    service = build_service(config.credentials_path)
    targets = fetch_sheet_titles(service, config.spreadsheet_id)
    print(f"Вкладок в таблице: {len(targets)}")
    grids = fetch_grids(service, config.spreadsheet_id, targets)

    data: list[dict] = []
    total_cells = 0
    for title in targets:
        rows, tables = grids.get(title, ([], []))
        updates, checks, dropdowns = build_updates(title, rows, config.reset_to, tables)
        cells = checks + dropdowns
        if cells:
            data.extend(updates)
            total_cells += cells
            parts = []
            if checks:
                parts.append(f"снято галочек: {checks}")
            if dropdowns:
                parts.append(f"списков -> {config.reset_to}: {dropdowns}")
            print(f"  {title}: {', '.join(parts)}")
        else:
            print(f"  {title}: изменений нет")

    if not data:
        print("Нечего сбрасывать.")
        return 0

    service.spreadsheets().values().batchUpdate(
        spreadsheetId=config.spreadsheet_id,
        body={"valueInputOption": "USER_ENTERED", "data": data},
    ).execute()

    print(f"Готово: сброшено ячеек — {total_cells}.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Сброс чекбоксов и выпадающих списков в чеклистах"
    )
    parser.add_argument(
        "--config",
        default=str(Path(__file__).with_name("config.json")),
        help="путь к config.json",
    )
    parser.add_argument(
        "--spreadsheet",
        help="ссылка или ID таблицы; без этого аргумента скрипт спросит её сам",
    )
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    try:
        spreadsheet = (args.spreadsheet or "").strip() or ask_spreadsheet()
        config = load_config(Path(args.config), spreadsheet)
        return run(config)
    except ConfigError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1
    except HttpError as error:
        print(f"Google API вернул ошибку: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
