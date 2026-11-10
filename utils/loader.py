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

    from .storage import charger_fichiers, enregistrer_fichiers

    if uploaded is not None:
        file_bytes = uploaded.getvalue()
        nouveau = (uploaded.name, len(file_bytes)) != (st.session_state.get("file_name"), len(st.session_state.get("file_bytes", b"")))
        st.session_state["file_bytes"] = file_bytes
        st.session_state["file_name"] = uploaded.name
        if nouveau:
            # Classeur partagé : enregistré dans la base pour toutes les sessions et tous les utilisateurs.
            if enregistrer_fichiers("classeur_principal", [{"fichier": uploaded.name, "contenu": file_bytes}],
                                    f"classeur principal remplacé : {uploaded.name}"):
                st.session_state["file_source"] = "enregistré dans la base"
                st.toast(f"{uploaded.name} enregistré dans la base de données", icon="💾")
            else:
                st.session_state["file_source"] = "session uniquement (non enregistré)"
    elif "file_bytes" not in st.session_state:
        enregistres = charger_fichiers("classeur_principal")
        if enregistres:
            st.session_state["file_bytes"] = enregistres[0]["contenu"]
            st.session_state["file_name"] = enregistres[0]["fichier"]
            st.session_state["file_source"] = f"base de données (déposé le {enregistres[0]['maj'][:10]})"
        elif DEFAULT_PATH.exists():
            st.session_state["file_bytes"] = DEFAULT_PATH.read_bytes()
            st.session_state["file_name"] = DEFAULT_PATH.name
            st.session_state["file_source"] = "classeur par défaut de l'application"
        else:
            st.sidebar.warning("Aucun fichier chargé pour le moment.")
            return None

    with st.sidebar:
        st.caption(f"Fichier actif : **{st.session_state.get('file_name', '—')}** — "
                   f"{st.session_state.get('file_source', '')}")

    try:
        contenu = st.session_state["file_bytes"]
        signature = (st.session_state.get("file_name"), len(contenu))
        if st.session_state.get("_classeur_lu") == signature:
            return load_workbook_data(contenu)  # déjà en cache : pas de barre
        from .ui import BarreChargement
        with BarreChargement("Lecture du classeur de données…", total=2) as barre:
            barre.etape("Ouverture du classeur")
            data = load_workbook_data(contenu)
            barre.etape("Classeur chargé")
        st.session_state["_classeur_lu"] = signature
        return data
    except Exception as exc:  # noqa: BLE001
        st.error(f"Impossible de lire ce classeur : {exc}")
        return None
