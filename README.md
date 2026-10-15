# Сброс статусов чеклистов в `test`

Скрипт проходит по всем вкладкам Google-таблицы, включая скрытые, и сбрасывает поля по их типу:
галочку снимает, в выпадающем списке ставит значение из `reset_to`.
Ссылки, названия вкладок и сводная страница не важны — подходит любая таблица.
Так же обрабатываются колонки таблиц Google Sheets с типом «галочка» или «выпадающий список»:
у них тип задан на всю колонку. Обычный текст не меняется.

## Установка

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Активировать окружение не обязательно: `reset_status.bat` сам берёт Python из `.venv`.
Если хочется `Activate.ps1`, а PowerShell пишет «выполнение сценариев отключено»,
разреши скрипты для своего пользователя:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
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
| `credentials_path` | Путь к JSON-ключу service account |
| `reset_to` | Что записать в выпадающий список. У чекбокса галочка просто снимается |

## Запуск

```powershell
.venv\Scripts\python.exe reset_status.py
```

Или двойной клик по `reset_status.bat`. Скрипт спросит ссылку. Вставь URL таблицы и нажми Enter.

Опционально ссылку можно передать сразу, без запроса:

```powershell
python reset_status.py --config other-config.json
python reset_status.py --spreadsheet https://docs.google.com/spreadsheets/d/<ID>/edit
```

Скрипт печатает, сколько ячеек изменено на каждой вкладке, и итоговую сумму.
`config.json` и `credentials.json` в git не попадают.

## Проверка логики без доступа к таблице

`selfcheck.py` прогоняет разбор ссылки на таблицу и сборку диапазонов по типу поля
на синтетических данных — доступ в Google не нужен:

```powershell
python selfcheck.py
```
