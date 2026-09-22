# Сброс статусов чеклистов в `test`

Скрипт читает сводную вкладку Google-таблицы, проходит по гиперссылкам из колонки «Название»
на вкладки внутри того же документа и сбрасывает статусы `pass`/`fail` в `test` —
как в самих чеклистах, так и в колонке статуса сводной вкладки.

## Установка

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Доступ к таблице

1. Создай проект в [Google Cloud Console](https://console.cloud.google.com/).
2. Включи **Google Sheets API** (APIs & Services -> Library -> Google Sheets API -> Enable).
3. Создай service account (IAM & Admin -> Service Accounts -> Create service account).
4. В карточке service account: Keys -> Add key -> Create new key -> JSON.
   Скачанный файл положи рядом со скриптом как `credentials.json`.
5. Скопируй email service account (вида `name@project.iam.gserviceaccount.com`)
   и расшарь на него таблицу с правами **Редактор**.

## Настройка

```powershell
copy config.example.json config.json
```

В `config.json`:

| Поле | Описание |
| --- | --- |
| `spreadsheet_id` | ID таблицы из URL: `docs.google.com/spreadsheets/d/<ID>/edit` |
| `index_sheet` | Имя сводной вкладки со списком чеклистов и ссылками |
| `credentials_path` | Путь к JSON-ключу service account |
| `status_headers` | Заголовки, по которым ищется колонка статуса |
| `reset_from` | Значения, которые нужно сбрасывать (регистр не важен) |
| `reset_to` | Значение, на которое меняем |

## Запуск

```powershell
python reset_status.py
```

Опционально:

```powershell
python reset_status.py --config other-config.json
python reset_status.py --spreadsheet https://docs.google.com/spreadsheets/d/<ID>/edit
```

Скрипт печатает, сколько ячеек изменено на каждой вкладке, и итоговую сумму.
`config.json` и `credentials.json` в git не попадают.

## Проверка логики без доступа к таблице

`selfcheck.py` прогоняет разбор ссылок, поиск колонки статуса и сборку диапазонов
на синтетических данных — доступ в Google не нужен:

```powershell
python selfcheck.py
```
