# PLX → long.csv

Streamlit-приложение: принимает учебный план `.plx` и отдаёт `long.csv`
(длинный формат — каждая строка = дисциплина в конкретном семестре).

## Файлы

- `app.py` — Streamlit-интерфейс (загрузка `.plx`, превью, скачивание `long.csv`).
- `long_maker.py` — вся логика разбора `.plx` и сборки long-формата (без зависимостей, кроме стандартной библиотеки).
- `requirements.txt` — зависимости.

## Запуск

```bash
cd long-maker-app
pip install -r requirements.txt
streamlit run app.py
```

Откроется в браузере. Загрузите `.plx`, при необходимости выберите профиль
(если в плане их несколько) и нажмите «Скачать long.csv».

## Использование как библиотеки

```python
from long_maker import plx_to_long, rows_to_csv

info, rows = plx_to_long("plan.plx")      # путь, bytes или file-like
csv_text = rows_to_csv(rows)
```
