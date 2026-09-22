"""Сброс статусов чеклистов Google Sheets в `test`.

Скрипт читает сводную вкладку, проходит по гиперссылкам из первой колонки
на вкладки того же документа и меняет статусы pass/fail на test.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
HEADER_SEARCH_ROWS = 5
SPREADSHEET_URL_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
GID_RE = re.compile(r"[#&?]gid=(\d+)")
HYPERLINK_FORMULA_RE = re.compile(r'HYPERLINK\(\s*"([^"]+)"', re.IGNORECASE)

DEFAULTS = {
    "index_sheet": "Чеклисты",
    "credentials_path": "credentials.json",
    "status_headers": ["Статус", "Чеклист", "Status"],
    "reset_from": ["pass", "fail"],
    "reset_to": "test",
}


class ConfigError(Exception):
    """Проблема с конфигурацией или доступом."""


@dataclass
class Config:
    spreadsheet_id: str
    index_sheet: str
    credentials_path: Path
    status_headers: list[str]
    reset_from: list[str]
    reset_to: str


@dataclass
class SheetLink:
    """Ссылка на вкладку из сводного списка."""

    title: str
    gid: int
    label: str


def normalize(value: object) -> str:
    return str(value).strip().lower() if value is not None else ""


def extract_spreadsheet_id(raw: str) -> str:
    match = SPREADSHEET_URL_RE.search(raw)
    return match.group(1) if match else raw.strip()


def load_config(config_path: Path, spreadsheet_override: str | None) -> Config:
    if not config_path.exists():
        raise ConfigError(
            f"Не найден {config_path}. Скопируй config.example.json в {config_path.name} "
            "и заполни spreadsheet_id."
        )

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    spreadsheet_raw = spreadsheet_override or raw.get("spreadsheet_id", "")
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_raw)
    if not spreadsheet_id:
        raise ConfigError("В конфиге не задан spreadsheet_id.")

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
        index_sheet=raw.get("index_sheet", DEFAULTS["index_sheet"]),
        credentials_path=credentials_path,
        status_headers=raw.get("status_headers", DEFAULTS["status_headers"]),
        reset_from=raw.get("reset_from", DEFAULTS["reset_from"]),
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


def fetch_sheet_titles(service, spreadsheet_id: str) -> dict[int, str]:
    response = (
        service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets.properties(sheetId,title)")
        .execute()
    )
    return {
        sheet["properties"]["sheetId"]: sheet["properties"]["title"]
        for sheet in response.get("sheets", [])
    }


def cell_link(cell: dict) -> str | None:
    """Гиперссылка ячейки: cell link, rich text или формула HYPERLINK."""
    if cell.get("hyperlink"):
        return cell["hyperlink"]

    for run in cell.get("textFormatRuns", []):
        uri = run.get("format", {}).get("link", {}).get("uri")
        if uri:
            return uri

    formula = cell.get("userEnteredValue", {}).get("formulaValue", "")
    match = HYPERLINK_FORMULA_RE.search(formula)
    return match.group(1) if match else None


def collect_links(
    service, config: Config, sheet_titles: dict[int, str]
) -> tuple[list[SheetLink], list[str]]:
    """Достаёт ссылки на вкладки из первой колонки сводного листа."""
    response = (
        service.spreadsheets()
        .get(
            spreadsheetId=config.spreadsheet_id,
            ranges=[f"{quote_sheet(config.index_sheet)}!A:A"],
            includeGridData=True,
            fields=(
                "sheets(data(rowData(values("
                "hyperlink,formattedValue,userEnteredValue,textFormatRuns))))"
            ),
        )
        .execute()
    )

    sheets = response.get("sheets", [])
    if not sheets:
        raise ConfigError(f"Вкладка «{config.index_sheet}» не найдена в таблице.")

    rows = sheets[0].get("data", [{}])[0].get("rowData", [])
    links: list[SheetLink] = []
    skipped: list[str] = []
    seen_gids: set[int] = set()

    for row in rows:
        values = row.get("values", [])
        if not values:
            continue
        cell = values[0]
        label = cell.get("formattedValue", "").strip()
        url = cell_link(cell)
        if not url:
            continue

        target_id = extract_spreadsheet_id(url)
        if target_id and target_id != config.spreadsheet_id and "/spreadsheets/d/" in url:
            skipped.append(f"{label or url}: ссылка на другую таблицу")
            continue

        gid_match = GID_RE.search(url)
        if not gid_match:
            skipped.append(f"{label or url}: в ссылке нет gid")
            continue

        gid = int(gid_match.group(1))
        if gid in seen_gids:
            continue

        title = sheet_titles.get(gid)
        if title is None:
            skipped.append(f"{label or url}: вкладка с gid={gid} не найдена")
            continue

        seen_gids.add(gid)
        links.append(SheetLink(title=title, gid=gid, label=label or title))

    return links, skipped


def find_status_column(grid: Sequence[Sequence[str]], headers: Iterable[str]) -> tuple[int, int] | None:
    """Возвращает (индекс строки заголовка, индекс колонки статуса)."""
    wanted = {normalize(header) for header in headers}
    for row_index, row in enumerate(grid[:HEADER_SEARCH_ROWS]):
        for col_index, value in enumerate(row):
            if normalize(value) in wanted:
                return row_index, col_index
    return None


def build_updates(
    sheet_title: str, grid: Sequence[Sequence[str]], config: Config
) -> list[dict]:
    """Готовит ValueRange на каждый непрерывный блок ячеек pass/fail."""
    found = find_status_column(grid, config.status_headers)
    if found is None:
        return []

    header_row, status_col = found
    reset_from = {normalize(value) for value in config.reset_from}
    letter = column_letter(status_col)

    updates: list[dict] = []
    block_start: int | None = None

    def flush(end_row: int) -> None:
        nonlocal block_start
        if block_start is None:
            return
        first = block_start + 1
        last = end_row + 1
        updates.append(
            {
                "range": f"{quote_sheet(sheet_title)}!{letter}{first}:{letter}{last}",
                "values": [[config.reset_to] for _ in range(first, last + 1)],
            }
        )
        block_start = None

    for row_index in range(header_row + 1, len(grid)):
        row = grid[row_index]
        value = row[status_col] if status_col < len(row) else ""
        if normalize(value) in reset_from:
            if block_start is None:
                block_start = row_index
        else:
            flush(row_index - 1)

    flush(len(grid) - 1)
    return updates


def fetch_grids(
    service, spreadsheet_id: str, titles: Sequence[str]
) -> dict[str, list[list[str]]]:
    response = (
        service.spreadsheets()
        .values()
        .batchGet(
            spreadsheetId=spreadsheet_id,
            ranges=[quote_sheet(title) for title in titles],
            majorDimension="ROWS",
        )
        .execute()
    )
    return {
        title: value_range.get("values", [])
        for title, value_range in zip(titles, response.get("valueRanges", []))
    }


def run(config: Config) -> int:
    service = build_service(config.credentials_path)
    sheet_titles = fetch_sheet_titles(service, config.spreadsheet_id)
    links, skipped = collect_links(service, config, sheet_titles)

    print(f"Найдено чеклистов по ссылкам: {len(links)}")
    for note in skipped:
        print(f"  пропуск -> {note}")

    targets = [config.index_sheet] + [
        link.title for link in links if link.title != config.index_sheet
    ]
    grids = fetch_grids(service, config.spreadsheet_id, targets)

    data: list[dict] = []
    total_cells = 0
    for title in targets:
        updates = build_updates(title, grids.get(title, []), config)
        cells = sum(len(update["values"]) for update in updates)
        if cells:
            data.extend(updates)
            total_cells += cells
            print(f"  {title}: {cells} ячеек -> {config.reset_to}")
        else:
            print(f"  {title}: изменений нет")

    if not data:
        print("Нечего сбрасывать.")
        return 0

    service.spreadsheets().values().batchUpdate(
        spreadsheetId=config.spreadsheet_id,
        body={"valueInputOption": "USER_ENTERED", "data": data},
    ).execute()

    print(f"Готово: {total_cells} ячеек сброшено в {config.reset_to}.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Сброс статусов чеклистов в test")
    parser.add_argument(
        "--config",
        default=str(Path(__file__).with_name("config.json")),
        help="путь к config.json",
    )
    parser.add_argument(
        "--spreadsheet",
        help="ID или URL таблицы, перекрывает значение из конфига",
    )
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    try:
        config = load_config(Path(args.config), args.spreadsheet)
        return run(config)
    except ConfigError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1
    except HttpError as error:
        print(f"Google API вернул ошибку: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
