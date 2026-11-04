import plotly.express as px
import streamlit as st

from utils.data import NAVY, BLUE, GOLD, CATEGORICAL
from utils.loader import get_data
from utils.ui import PAGE_ICON, inject_base_style, section_title, plotly_base_layout, render_sidebar_footer

st.set_page_config(page_title="Répartition régionale — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()

data = get_data()
if data is None:
    st.stop()

st.title("🌍 Répartition géographique du parc solaire")

tab1, tab2 = st.tabs(["Par antenne (transmis AER)", "Par région / département / arrondissement"])

with tab1:
    rep = data.repartition
    if rep is not None and not rep.empty:
        c1, c2, c3 = st.columns(3)
        f_antenne = c1.multiselect("Antenne", sorted(rep["Antenne proposée"].dropna().unique()), key="rep_antenne")
        f_region = c2.multiselect("Région", sorted(rep["Région"].dropna().unique()), key="rep_region")
        f_phase = c3.multiselect("Phase", sorted(rep["Phase"].dropna().unique()), key="rep_phase")
        view = rep.copy()
        if f_antenne:
            view = view[view["Antenne proposée"].isin(f_antenne)]
        if f_region:
            view = view[view["Région"].isin(f_region)]
        if f_phase:
            view = view[view["Phase"].isin(f_phase)]
        st.caption(f"{len(view)} site(s) sur {len(rep)}")

        c1, c2 = st.columns(2)
        with c1:
            agg = view.groupby("Antenne proposée", as_index=False)["Puissance (kWc)"].sum()
            fig = px.treemap(agg, path=["Antenne proposée"], values="Puissance (kWc)",
                              color="Puissance (kWc)", color_continuous_scale=[BLUE, NAVY],
                              title="Puissance (kWc) par antenne")
            fig = plotly_base_layout(fig, legend=False)
            st.plotly_chart(fig, width="stretch")
        with c2:
            agg2 = view.groupby("Département", as_index=False).size().sort_values("size", ascending=False).head(15)
            fig = px.bar(agg2, x="Département", y="size", color_discrete_sequence=[GOLD],
                         title="Top 15 départements par nombre de sites")
            fig = plotly_base_layout(fig, legend=False)
            fig.update_layout(yaxis_title="Sites")
            st.plotly_chart(fig, width="stretch")

        st.dataframe(view, width="stretch", hide_index=True, height=380)
        st.download_button("⬇️ Télécharger (CSV)", view.to_csv(index=False).encode("utf-8"),
                            "repartition_antenne.csv", "text/csv")
    else:
        st.warning("Feuille « Répartition par antenne » introuvable ou vide.")

with tab2:
    syn = data.synthese_region
    if syn is not None and not syn.empty:
        st.caption("Tableau à deux niveaux : une ligne « sous-total région » suivie de ses lignes détail "
                   "par arrondissement. Les graphiques utilisent uniquement les sous-totaux région pour "
                   "éviter tout double comptage.")
        f_region = st.multiselect("Région", sorted(syn["Région"].dropna().unique()), key="syn_region")
        view = syn.copy()
        if f_region:
            view = view[view["Région"].isin(f_region)]

        region_level = view[view["Niveau"] == "Sous-total région"]
        c1, c2 = st.columns(2)
        with c1:
            fig = px.bar(region_level.sort_values("Nb sites", ascending=False), x="Région", y="Nb sites",
                         color_discrete_sequence=[NAVY], title="Nombre de sites par région")
            fig = plotly_base_layout(fig, legend=False)
            st.plotly_chart(fig, width="stretch")
        with c2:
            fig = px.pie(region_level, names="Région", values="Puissance totale (kWc)", hole=0.35,
                         color_discrete_sequence=CATEGORICAL, title="Puissance totale (kWc) par région")
            fig = plotly_base_layout(fig)
            st.plotly_chart(fig, width="stretch")

        detail_level = view[view["Niveau"] == "Détail (arrondissement)"]
        if not detail_level.empty:
            top_dept = detail_level.groupby("Département", as_index=False)["Nb sites"].sum().sort_values(
                "Nb sites", ascending=False).head(15)
            fig = px.bar(top_dept, x="Département", y="Nb sites", color_discrete_sequence=[GOLD],
                         title="Top 15 départements par nombre de sites (sélection courante)")
            fig = plotly_base_layout(fig, legend=False)
            st.plotly_chart(fig, width="stretch")

        st.dataframe(view, width="stretch", hide_index=True, height=380)
        st.download_button("⬇️ Télécharger (CSV)", view.to_csv(index=False).encode("utf-8"),
                            "synthese_region.csv", "text/csv")
    else:
        st.warning("Feuille « Synthèse par région » introuvable ou vide.")

render_sidebar_footer(data.generated_on)
