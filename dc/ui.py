"""Éléments d'interface communs aux pages du module Data Center : droits, couleurs, en-tête."""
from __future__ import annotations

import streamlit as st

from utils.auth import auth_desactivee, role

ROLES_LECTURE = {"admin", "direction", "sdmse", "technicien", "lecteur"}
ROLES_INSPECTION = {"admin", "direction", "sdmse", "technicien"}
ROLES_GESTION = {"admin", "sdmse"}          # registre, seuils, listes de contrôle
ROLES_SENSIBLE = {"admin", "sdmse"}         # adressage IP, constats de sécurité

COULEURS = {"OK": "#16A34A", "Information": "#2563EB", "Avertissement": "#D97706", "Critique": "#DC2626", "—": "#9CA3AF"}
ICONES = {"OK": "🟢", "Information": "🔵", "Avertissement": "🟠", "Critique": "🔴", "—": "⚪"}


def peut(roles: set[str]) -> bool:
    return auth_desactivee() or role() in roles


def exiger_lecture() -> None:
    if not peut(ROLES_LECTURE):
        st.warning("🔒 Votre profil ne donne pas accès au module Data Center.")
        st.stop()


@st.cache_resource(show_spinner=False)
def _init(url: str) -> dict:
    from . import depot
    return depot.initialiser()


def initialiser() -> None:
    """Crée les tables et charge le contenu initial une fois par processus."""
    from . import depot
    eng = depot.moteur()
    _init(str(eng.url))


def style() -> None:
    st.markdown("""<style>
.dc-bandeau{background:linear-gradient(90deg,#0F172A,#1F3864);color:#fff;border-radius:14px;padding:.9rem 1.2rem;margin-bottom:.8rem}
.dc-bandeau h2{color:#fff;margin:0;font-size:1.35rem}.dc-bandeau p{margin:.15rem 0 0 0;opacity:.85;font-size:.88rem}
.dc-sys{border-radius:12px;padding:.7rem .8rem;color:#fff;min-height:104px}
.dc-sys b{display:block;font-size:.95rem}.dc-sys span{font-size:.8rem;opacity:.95}
.dc-badge{display:inline-block;border-radius:10px;padding:0 .5rem;color:#fff;font-size:.78rem;font-weight:600}
</style>""", unsafe_allow_html=True)


def bandeau(titre: str, sous_titre: str) -> None:
    st.markdown(f"<div class='dc-bandeau'><h2>{titre}</h2><p>{sous_titre}</p></div>", unsafe_allow_html=True)


def badge(sev: str) -> str:
    return f"<span class='dc-badge' style='background:{COULEURS.get(sev, '#9CA3AF')}'>{sev}</span>"


def colorer_severite(v):
    c = COULEURS.get(v)
    return f"background-color:{c};color:white;font-weight:600" if c and v != "—" else ""
