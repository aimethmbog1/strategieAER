import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from utils.data import NAVY, BLUE, GOLD, CATEGORICAL
from utils.loader import get_data
from utils.ui import PAGE_ICON, inject_base_style, section_title, plotly_base_layout, kpi_row, render_sidebar_footer

st.set_page_config(page_title="Parc solaire — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()

data = get_data()
if data is None:
    st.stop()

st.title("🛰️ Parc solaire — 499 sites")
st.info("🗺️ Pour la carte interactive complète (sites, antennes, distances, personnel), "
        "ouvrez **« Carte d'électrification »** dans le menu de gauche.")

# =====================================================================
# Dimensionnement par antenne
# =====================================================================
section_title("DIMENSIONNEMENT DU PERSONNEL PAR ANTENNE")
det = data.antennes_detail
if det is not None and not det.empty:
    kpi_row([
        ("Sites totaux", f"{int(det['Nb sites'].sum()):,}".replace(",", " "), None),
        ("Puissance totale (kWc)", f"{det['Puissance totale (kWc)'].sum():,.1f}".replace(",", " "), None),
        ("Effectif recommandé", f"{int(det['Effectif total'].sum()):,}", None),
        ("Antennes", str(len(det)), None),
    ])
    st.dataframe(det, width="stretch", hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        fig = px.bar(det, x="Antenne", y="Nb sites", color_discrete_sequence=[BLUE], title="Sites par antenne")
        fig = plotly_base_layout(fig, legend=False)
        st.plotly_chart(fig, width="stretch")
    with c2:
        fig = px.pie(det, names="Antenne", values="Puissance totale (kWc)", hole=0.35,
                     color_discrete_sequence=CATEGORICAL, title="Puissance installée par antenne")
        fig.update_traces(textinfo="percent")
        fig = plotly_base_layout(fig)
        st.plotly_chart(fig, width="stretch")

    c3, c4 = st.columns(2)
    with c3:
        fig = go.Figure()
        for col, color in zip(["Chef + admin", "Ingénieurs techniques", "Agents communautaires"],
                               [NAVY, BLUE, GOLD]):
            fig.add_bar(name=col, x=det["Antenne"], y=det[col], marker_color=color)
        fig.update_layout(barmode="stack")
        fig = plotly_base_layout(fig)
        fig.update_layout(title="Effectif recommandé, par fonction")
        st.plotly_chart(fig, width="stretch")
    with c4:
        fig = px.bar(det.sort_values("Sites par agent"), x="Antenne", y="Sites par agent",
                     color_discrete_sequence=[GOLD], title="Charge relative (sites / agent)")
        fig = plotly_base_layout(fig, legend=False)
        st.plotly_chart(fig, width="stretch")
else:
    st.warning("Feuille « Antennes — Détail solaire » introuvable ou vide.")

st.write("")

# =====================================================================
# Liste des 499 sites — filtrable + carte
# =====================================================================
section_title("LISTE DES SITES — FILTRES & TABLEAU")
sites = data.sites
if sites is not None and not sites.empty:
    fc1, fc2, fc3, fc4 = st.columns(4)
    antennes = sorted(sites["Antenne proposée"].dropna().unique())
    regions = sorted(sites["Région"].dropna().unique())
    phases = sorted(sites["Phase"].dropna().unique())
    f_antenne = fc1.multiselect("Antenne", antennes, default=[])
    f_region = fc2.multiselect("Région", regions, default=[])
    f_phase = fc3.multiselect("Phase", phases, default=[])
    f_search = fc4.text_input("Rechercher un site")

    view = sites.copy()
    if f_antenne:
        view = view[view["Antenne proposée"].isin(f_antenne)]
    if f_region:
        view = view[view["Région"].isin(f_region)]
    if f_phase:
        view = view[view["Phase"].isin(f_phase)]
    if f_search:
        view = view[view["Nom du site"].astype(str).str.contains(f_search, case=False, na=False)]

    st.caption(f"{len(view)} site(s) affiché(s) sur {len(sites)}")

    tab_table, tab_charts = st.tabs(["📋 Tableau", "📊 Répartition"])
    with tab_table:
        st.dataframe(view, width="stretch", hide_index=True, height=480)
        st.download_button("⬇️ Télécharger cette sélection (CSV)", view.to_csv(index=False).encode("utf-8"),
                            "sites_filtrés.csv", "text/csv")
    with tab_charts:
        cc1, cc2 = st.columns(2)
        with cc1:
            by_antenne = view.groupby("Antenne proposée", as_index=False)["Puissance (kWc)"].sum()
            fig = px.bar(by_antenne.sort_values("Puissance (kWc)", ascending=False),
                         x="Antenne proposée", y="Puissance (kWc)", color_discrete_sequence=[NAVY])
            fig = plotly_base_layout(fig, legend=False)
            fig.update_layout(title="Puissance (kWc) — sélection courante")
            st.plotly_chart(fig, width="stretch")
        with cc2:
            by_region = view.groupby("Région", as_index=False).size()
            fig = px.bar(by_region.sort_values("size", ascending=False),
                         x="Région", y="size", color_discrete_sequence=[GOLD])
            fig = plotly_base_layout(fig, legend=False)
            fig.update_layout(title="Nombre de sites par région — sélection courante", yaxis_title="Sites")
            st.plotly_chart(fig, width="stretch")
else:
    st.warning("Feuille « Données sites » introuvable ou vide.")

render_sidebar_footer(data.generated_on)
