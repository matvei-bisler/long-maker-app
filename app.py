"""
Streamlit-приложение: учебный план .plx → long.csv.

Запуск:  streamlit run app.py
"""

import pandas as pd
import streamlit as st

from long_maker import plx_to_long, rows_to_csv

st.set_page_config(page_title="PLX → long.csv", page_icon="📑", layout="wide")

st.title("📑 PLX → long.csv")
st.caption(
    "Загрузите учебный план в формате `.plx` — приложение соберёт `long.csv` "
    "(каждая строка = дисциплина в конкретном семестре) и даст его скачать."
)

uploaded = st.file_uploader("Учебный план (.plx)", type=["plx", "xml"])

if uploaded is None:
    st.info("Перетащите сюда `.plx` файл, чтобы начать.")
    st.stop()

# Разбор .plx
try:
    data = uploaded.getvalue()
    # Сначала смотрим, сколько профилей, чтобы дать выбор
    info_probe, _ = plx_to_long(data, profile_index=0)
    profiles = info_probe["profiles"]
except Exception as exc:  # noqa: BLE001
    st.error(f"Не удалось разобрать файл: {exc}")
    st.stop()

profile_index = 0
if len(profiles) > 1:
    choice = st.selectbox(
        "Профиль (в плане их несколько)",
        options=list(range(len(profiles))),
        format_func=lambda i: profiles[i],
    )
    profile_index = int(choice)

info, rows = plx_to_long(data, profile_index=profile_index)

if not rows:
    st.warning("Дисциплины не найдены — проверьте, что это корректный файл учебного плана.")
    st.stop()

# Метаданные
c1, c2, c3 = st.columns(3)
c1.metric("Направление", info["direction_code"] or "—")
c2.metric("Дисциплин", info["discipline_count"])
c3.metric("Строк в long.csv", info["row_count"])

st.write(f"**Направление:** {info['direction']}")
st.write(f"**Программа:** {info['program_name']}")

# Превью
df = pd.DataFrame(rows)
st.subheader("Предпросмотр")
st.dataframe(df, use_container_width=True, hide_index=True)

# Скачивание
csv_text = rows_to_csv(rows)
default_name = (info["direction_code"] or "plan").replace(" ", "_")
st.download_button(
    label="⬇️ Скачать long.csv",
    data=csv_text.encode("utf-8"),
    file_name=f"{default_name}_long.csv",
    mime="text/csv",
    type="primary",
)
