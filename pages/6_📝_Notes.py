import re

import streamlit as st

from utils.loader import get_data
from utils.ui import PAGE_ICON, inject_base_style, render_sidebar_footer

st.set_page_config(page_title="Notes & méthodologie — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()

data = get_data()
if data is None:
    st.stop()

st.title("📝 Notes & méthodologie")

texts = data.notes_text
if not texts:
    st.warning("Feuille « Notes & méthodologie » introuvable ou vide.")
    st.stop()

SECTION_RE = re.compile(r"^[A-Z] ?(bis|ter)?\.\s")

search = st.text_input("🔎 Rechercher dans les notes")

for t in texts:
    if search and search.lower() not in t.lower():
        continue
    if t.isupper() and len(t) > 20:
        st.header(t)
    elif SECTION_RE.match(t):
        st.subheader(t)
    else:
        st.markdown(f"- {t}")

render_sidebar_footer(data.generated_on)
