# rag-assistant

Короткое описание: что делает проект и зачем.

## Запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # заполнить своими значениями
rag-assistant           # или: python -m rag_assistant
```

## Тесты и линтер

```bash
pytest
ruff check .
```

## Структура

```
src/rag_assistant/   код
tests/              тесты
```
