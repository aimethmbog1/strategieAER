import pandas as pd
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
st.caption("État de fonctionnement des centrales, synthèse de la maintenance (le détail est dans la GMAO) et "
           "dimensionnement des équipes. Pour la carte interactive, ouvrez **« Carte d'électrification »**.")

# =====================================================================
# État de fonctionnement du parc + suivi de la maintenance
# =====================================================================
from utils import maintenance as mt
from utils import gmao_ui
from utils import gmao_core as gc
import os as _os
PAGE_GMAO = next("vues/" + f for f in sorted(_os.listdir(_os.path.join(_os.path.dirname(__file__)))) if f.startswith("23_"))

ref_sites = mt.referentiel_sites(data.sites) if data.sites is not None and not data.sites.empty else None
if ref_sites is not None:
    section_title("ÉTAT DE FONCTIONNEMENT DU PARC")
    gc.migrer_interventions()
    _bi = gc.table("gmao_bi")
    arrets_bi = set(_bi.loc[_bi["statut"].isin(gc.STATUTS_BI_OUVERTS) & _bi["centrale_arret"], "site_id"].dropna())
    classes = gmao_ui.classes_sites(ref_sites)
    if classes is None:
        classes = pd.Series("Non renseigné", index=ref_sites["site_id"])
    classes = classes.where(~classes.index.isin(arrets_bi), "À l'arrêt")
    etat = mt.etat_parc(ref_sites, mt.registre_vide(), classes)
    tot = etat[etat["Phase"] == "Total parc"].iloc[0]
    _f = lambda x, d=1: f"{x:,.{d}f}".replace(",", " ").replace(".", ",")
    kpi_row([
        ("Centrales en service", f"{int(tot['Fonctionnelles'])} / {int(tot['Centrales'])}",
         f"{_f(tot['% centrales en service'])} % du parc"),
        ("dont partiel", str(int(tot["Fonctionnement partiel"])), None),
        ("Centrales à l'arrêt", str(int(tot["À l'arrêt"])), None),
        ("État non renseigné", str(int(tot["Non renseigné"])), None),
        ("kWc en service", _f(tot["Puissance en service (kWc)"]),
         f"{_f(tot['% puissance en service'])} % de {_f(tot['Puissance totale (kWc)'])} kWc"),
    ])
    st.dataframe(etat, width="stretch", hide_index=True,
                 column_config={**{c: st.column_config.NumberColumn(format="localized") for c in
                                   ["Puissance totale (kWc)", "Puissance en service (kWc)", "Puissance à l'arrêt (kWc)"]},
                                **{c: st.column_config.ProgressColumn(c, format="%.1f %%", min_value=0, max_value=100)
                                   for c in ["% centrales en service", "% puissance en service"]}})
    ph = etat[etat["Phase"] != "Total parc"]
    c1, c2 = st.columns(2)
    with c1:
        fig = go.Figure()
        fig.add_bar(name="H24", x=ph["Phase"], y=ph["Fonctionnelles (H24)"], marker_color=NAVY)
        fig.add_bar(name="Partiel", x=ph["Phase"], y=ph["Fonctionnement partiel"], marker_color=BLUE)
        fig.add_bar(name="À l'arrêt", x=ph["Phase"], y=ph["À l'arrêt"], marker_color=GOLD)
        fig.add_bar(name="Non renseigné", x=ph["Phase"], y=ph["Non renseigné"], marker_color="#C7CCD1")
        fig.update_layout(barmode="stack")
        fig = plotly_base_layout(fig, height=300)
        fig.update_layout(title="Centrales par phase et par état", legend=dict(orientation="h", y=-0.3))
        st.plotly_chart(fig, width="stretch")
    with c2:
        fig = go.Figure()
        fig.add_bar(name="En service", x=ph["Phase"], y=ph["Puissance en service (kWc)"], marker_color=NAVY)
        fig.add_bar(name="À l'arrêt", x=ph["Phase"], y=ph["Puissance à l'arrêt (kWc)"], marker_color=GOLD)
        fig.add_bar(name="Non renseigné", x=ph["Phase"], y=ph["Puissance totale (kWc)"] - ph["Puissance en service (kWc)"]
                    - ph["Puissance à l'arrêt (kWc)"], marker_color="#C7CCD1")
        fig.update_layout(barmode="stack")
        fig = plotly_base_layout(fig, height=300)
        fig.update_layout(title="Puissance par phase (kWc)", separators=", ", legend=dict(orientation="h", y=-0.3))
        st.plotly_chart(fig, width="stretch")
    st.caption("État issu du dernier journal de maintenance importé (Phases 1 et 2) ; « en service » = fonctionnement H24 "
               "ou partiel (plages horaires réduites). Un bon d'intervention ouvert déclarant la centrale à l'arrêt prime : la centrale "
               "est comptée à l'arrêt. Les centrales de Phase 3, absentes des journaux, restent « non renseignées » tant "
               "qu'aucun état n'est importé ou saisi.")

    section_title("SUIVI DE LA MAINTENANCE")
    bi_ = gc.table("gmao_bi")
    di_ = gc.table("gmao_di")
    k = gc.kpis_bi(bi_, pd.Timestamp(gc.maintenant()).normalize())
    kpi_row([("Demandes nouvelles (DI)", str(int((di_["statut"] == "Nouvelle").sum())), None),
             ("BI ouverts", str(k["ouverts"]), None), ("BI en retard", str(k["en_retard"]), None),
             ("BI non affectés", str(k["non_affectes"]), None),
             ("Centrales à l'arrêt déclarées (BI)", str(len(arrets_bi)), None)])
    try:
        st.page_link(PAGE_GMAO, label="Ouvrir la GMAO : demandes et bons d'intervention, parc solaire en exploitation, préventif, "
                     "stocks, achats, budgets, ressources, analyses, mode terrain", icon="🔧")
    except Exception:  # noqa: BLE001 — lien indisponible hors navigation multipage
        st.info("🔧 Le détail de la maintenance est dans la page « GMAO Maintenance » du menu.")

# =====================================================================
# Dimensionnement par antenne
# =====================================================================
section_title("DIMENSIONNEMENT DU PERSONNEL PAR ANTENNE")
det = data.antennes_detail
if det is not None and not det.empty:
    kpi_row([
        ("Sites totaux", f"{int(det['Nb sites'].sum()):,}".replace(",", " "), None),
        ("Puissance totale (kWc)", f"{det['Puissance totale (kWc)'].sum():,.1f}".replace(",", " ").replace(".", ","), None),
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
