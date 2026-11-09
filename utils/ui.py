"""Composants d'interface et thème partagés par toutes les pages."""
from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go
import plotly.io as pio

from .data import NAVY, BLUE, GOLD, RED, GREEN, AMBER, GREY, CATEGORICAL, STATUS_COLORS

PAGE_ICON = "☀️"
APP_TITLE = "Tableau de bord AER — Parc solaire & Ressources humaines"


# Jetons d'habillage repris du design de tertullien.com (voir commentaire dans
# .streamlit/config.toml) — uniquement pour le « chrome » de l'app (cartes KPI,
# bandeaux de section, badges). Les couleurs des graphiques Plotly restent
# celles de utils/data.py (NAVY/BLUE/GOLD/STATUS_COLORS), volontairement non
# modifiées ici.
BRAND = "#14532D"          # vert Tertullien — titres de section, accents
BRAND_DARK = "#052E16"
SURFACE_ALT = "#F0FDF4"     # teinte menthe claire (sections alternées du site)
CARD_SHADOW = "0 1px 4px rgba(5,46,22,0.06)"
CARD_SHADOW_MD = "0 4px 16px rgba(5,46,22,0.10)"
HEADING_FONT = "'Outfit', 'Plus Jakarta Sans', sans-serif"


def inject_base_style():
    st.markdown(
        f"""
        <style>
        .block-container {{ padding-top: 1.6rem; padding-bottom: 3rem; }}

        /* Cartes KPI (st.metric) — style « feature card » du site de référence :
           fond blanc, coins arrondis, ombre légère teintée de vert plutôt que
           grise. S'applique automatiquement à tous les st.metric existants,
           sans changer leur code d'appel. */
        [data-testid="stMetric"] {{
            background: #FFFFFF;
            border: 1px solid {GREY}26;
            border-radius: 14px;
            padding: 1rem 1.1rem 0.9rem 1.1rem;
            box-shadow: {CARD_SHADOW};
        }}
        [data-testid="stMetricValue"] {{ font-size: 1.6rem; color: {BRAND_DARK}; font-family: {HEADING_FONT}; font-weight: 700; }}
        [data-testid="stMetricLabel"] {{ font-weight: 600; letter-spacing: .02em; }}

        .aer-kpi {{
            background: #FFFFFF;
            border: 1px solid {GREY}26;
            border-radius: 14px;
            padding: 0.9rem 1rem 0.7rem 1rem;
            box-shadow: {CARD_SHADOW};
        }}
        .aer-badge {{
            display: inline-block; padding: 0.2rem 0.7rem; border-radius: 999px;
            font-size: 0.78rem; font-weight: 700; color: white; letter-spacing: .01em;
        }}
        .aer-section-title {{
            background: {SURFACE_ALT}; color: {BRAND_DARK}; font-family: {HEADING_FONT};
            font-weight: 700; font-size: 1.05rem;
            padding: 0.55rem 0.9rem; border-radius: 12px; margin: 0.6rem 0 0.8rem 0;
        }}
        h1, h2, h3, h4 {{ font-family: {HEADING_FONT}; }}
        div[data-baseweb="tab-list"] {{ gap: 4px; }}
        [data-testid="stTab"] p {{ font-family: {HEADING_FONT}; font-weight: 600; }}
        [data-testid="stSidebarNavLink"] {{ border-radius: 10px; }}
        </style>
        """,
        unsafe_allow_html=True,
    )
    # Contrôle d'accès : chaque page appelle inject_base_style() juste après set_page_config,
    # ce qui en fait le point d'entrée unique de l'authentification (utils/auth.py).
    from .auth import require_login
    require_login()


def section_title(text: str):
    st.markdown(f'<div class="aer-section-title">{text}</div>', unsafe_allow_html=True)


def status_badge(status: str) -> str:
    color = STATUS_COLORS.get(status, GREY)
    return f'<span class="aer-badge" style="background:{color}">{status}</span>'


def plotly_base_layout(fig: go.Figure, height: int = 380, legend: bool = True) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=48, b=10),
        font=dict(family="Segoe UI, Arial, sans-serif", size=13, color="#2B2B2B"),
        title_font=dict(size=15, color=NAVY),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hoverlabel=dict(bgcolor="white", font_size=12),
    )
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(showgrid=True, gridcolor="rgba(31,56,100,0.08)", zeroline=False)
    return fig


def style_map(styler, func, subset=None):
    """Wrapper compatible pandas < 2.1 (Styler.applymap) et >= 2.1 / 3.x
    (Styler.map, applymap étant supprimé en pandas 3.0)."""
    if hasattr(styler, "map"):
        return styler.map(func, subset=subset)
    return styler.applymap(func, subset=subset)


class BarreChargement:
    """Barre de progression visible pendant un chargement de données, retirée à la fin.

    Usage :
        with BarreChargement("Lecture des fichiers…", total=3) as barre:
            ...; barre.etape("Fichier 1 lu")
    """

    def __init__(self, libelle: str = "Chargement des données…", total: int = 1, conteneur=None):
        self.total = max(int(total), 1)
        self.fait = 0
        self.libelle = libelle
        self._zone = (conteneur or st).empty()
        self._barre = self._zone.progress(0.0, text=f"⏳ {libelle}")

    def etape(self, texte: str | None = None, n: int = 1) -> None:
        self.fait = min(self.fait + n, self.total)
        pct = self.fait / self.total
        self._barre.progress(pct, text=f"⏳ {texte or self.libelle} — {round(pct * 100)} %")

    def fin(self) -> None:
        self._zone.empty()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.fin()
        return False


def kpi_row(items: list[tuple[str, str, str | None]]):
    """items: liste de (label, valeur, delta_ou_None)."""
    cols = st.columns(len(items))
    for col, (label, value, delta) in zip(cols, items):
        with col:
            st.metric(label, value, delta=delta)


def gauge_indicator(
    value: float, title: str, max_value: float = 100, suffix: str = "%",
    low_threshold: float = 40, high_threshold: float = 75,
    low_color: str = RED, mid_color: str = AMBER, high_color: str = GREEN,
    height: int = 320,
) -> go.Figure:
    """Jauge (« meter ») pour un ratio lu contre une limite (taux de
    couverture, taux de recouvrement, part solaire...) — plus lisible qu'un
    simple pourcentage en texte pour ce type de métrique. Les seuils bas/haut
    sont exprimés sur la même échelle que `value` (ex. en %)."""
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        number={"suffix": suffix, "font": {"size": 22, "color": NAVY}},
        title={"text": title, "font": {"size": 13, "color": NAVY}},
        gauge={
            "axis": {"range": [0, max_value], "tickwidth": 1, "tickcolor": GREY},
            "bar": {"color": NAVY, "thickness": 0.32},
            "bgcolor": "white",
            "borderwidth": 0,
            "steps": [
                {"range": [0, low_threshold], "color": f"{low_color}26"},
                {"range": [low_threshold, high_threshold], "color": f"{mid_color}26"},
                {"range": [high_threshold, max_value], "color": f"{high_color}26"},
            ],
        },
    ))
    fig.update_layout(
        height=height, margin=dict(l=30, r=30, t=60, b=50),
        font=dict(family="Segoe UI, Arial, sans-serif", color="#2B2B2B"),
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def render_sidebar_footer(generated_on: str):
    if st.session_state.get("storage_erreur"):
        st.sidebar.error("⚠️ " + st.session_state["storage_erreur"])
    st.sidebar.markdown("---")
    if generated_on:
        st.sidebar.caption(generated_on)
    st.sidebar.markdown("**Autres applications AER**  \n"
                        "[🔌 Statistiques des compteurs](https://aermeterdashboard.streamlit.app/)  \n"
                        "[🗂️ Suivi des dossiers (ERP)](https://aerapperp.streamlit.app/)")
    st.sidebar.caption("AER · Usage interne — accès journalisé. Voir « Mentions et confidentialité ».")
