"""Chargement du classeur, partagé par toutes les pages via st.session_state."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from .data import AERData, load_workbook_data

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data.xlsx"


def get_data() -> AERData | None:
    """Renvoie les données déjà chargées (session_state), ou tente de charger
    le fichier fourni par défaut avec l'application. Affiche l'uploader dans
    la barre latérale sur chaque page pour permettre de changer de fichier
    à tout moment."""
    with st.sidebar:
        st.markdown("### 📁 Source des données")
        uploaded = st.file_uploader(
            "Charger un autre classeur (.xlsx)", type=["xlsx"], key="uploader_global"
        )

    if uploaded is not None:
        file_bytes = uploaded.getvalue()
        st.session_state["file_bytes"] = file_bytes
        st.session_state["file_name"] = uploaded.name
    elif "file_bytes" not in st.session_state:
        if DEFAULT_PATH.exists():
            st.session_state["file_bytes"] = DEFAULT_PATH.read_bytes()
            st.session_state["file_name"] = DEFAULT_PATH.name
        else:
            st.sidebar.warning("Aucun fichier chargé pour le moment.")
            return None

    with st.sidebar:
        st.caption(f"Fichier actif : **{st.session_state.get('file_name', '—')}**")

    try:
        return load_workbook_data(st.session_state["file_bytes"])
    except Exception as exc:  # noqa: BLE001
        st.error(f"Impossible de lire ce classeur : {exc}")
        return None
