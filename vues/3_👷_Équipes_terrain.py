import plotly.express as px
import streamlit as st

from utils.data import NAVY, BLUE, GREEN, RED, CATEGORICAL
from utils.loader import get_data
from utils.personnel import get_effective_roster
from utils.ui import (
    PAGE_ICON, inject_base_style, section_title, plotly_base_layout, kpi_row,
    render_sidebar_footer, style_map,
)

st.set_page_config(page_title="Équipes terrain — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()

data = get_data()
if data is None:
    st.stop()

st.title("👷 Ressources humaines terrain — Équipes")

eq, unassigned_effectif = get_effective_roster(data.equipes_rows, data.unassigned)
if eq is None or eq.empty:
    st.warning("Feuille « Données - Équipes » introuvable ou vide.")
    st.stop()
st.caption("↔️ Les mouvements de personnel appliqués cette session (page « Organigramme ») sont déjà reflétés "
           "ci-dessous.")

STANDARD_ROLES = ["Ingénieur", "Technicien 1", "Technicien 2", "Chauffeur"]
standard = eq[eq["Rôle"].isin(STANDARD_ROLES)]
extra = eq[~eq["Rôle"].isin(STANDARD_ROLES)]
total = len(standard)
ok = int((standard["Statut"] == "OK").sum())
manque = int((standard["Statut"] == "MANQUE").sum())
kpi_row([
    ("Postes-types suivis (16 équipes × 4)", str(total), None),
    ("Postes pourvus", str(ok), None),
    ("Postes manquants", str(manque), None),
    ("Taux de couverture", f"{ok / total:.0%}" if total else "—", None),
])
if not extra.empty:
    st.caption(f"+ {len(extra)} agent(s) en personnel additionnel (hors profil-type à 4 postes), "
               "inclus dans le tableau ci-dessous mais exclus de ces indicateurs.")

st.write("")
section_title("ÉQUIPES PAR ZONE — FILTRES")

c1, c2, c3, c4 = st.columns(4)
antennes = sorted(eq["Antenne"].dropna().unique())
zones = sorted(eq["Zone"].dropna().unique()) if "Zone" in eq.columns else []
roles = sorted(eq["Rôle"].dropna().unique())
f_antenne = c1.multiselect("Antenne", antennes, default=[])
f_zone = c2.multiselect("Zone", zones, default=[], disabled=not zones)
f_role = c3.multiselect("Rôle", roles, default=[])
f_statut = c4.multiselect("Statut", ["OK", "MANQUE"], default=[])

c5, c6 = st.columns(2)
postes = sorted(eq["Poste (fichier RH)"].dropna().unique()) if "Poste (fichier RH)" in eq.columns else []
f_poste = c5.multiselect("Poste (fichier RH)", postes, default=[], disabled=not postes)
f_search = c6.text_input("Rechercher un nom")

view = eq.copy()
if f_antenne:
    view = view[view["Antenne"].isin(f_antenne)]
if f_zone:
    view = view[view["Zone"].isin(f_zone)]
if f_role:
    view = view[view["Rôle"].isin(f_role)]
if f_statut:
    view = view[view["Statut"].isin(f_statut)]
if f_poste:
    view = view[view["Poste (fichier RH)"].isin(f_poste)]
if f_search:
    view = view[view["Nom"].astype(str).str.contains(f_search, case=False, na=False)]

st.caption(f"{len(view)} ligne(s) affichée(s) sur {len(eq)}")


def style_statut(v):
    if v == "OK":
        return f"background-color:#D9EAD3;color:{GREEN};font-weight:600"
    if v == "MANQUE":
        return f"background-color:#F8D7DA;color:{RED};font-weight:600"
    return ""


st.dataframe(style_map(view.style, style_statut, subset=["Statut"]),
             width="stretch", hide_index=True, height=460)
st.download_button("⬇️ Télécharger cette sélection (CSV)", view.to_csv(index=False).encode("utf-8"),
                    "equipes_filtrées.csv", "text/csv")

st.write("")
c1, c2 = st.columns(2)
with c1:
    by_role = eq[eq["Statut"] == "MANQUE"].groupby(
        eq["Rôle"].str.replace(r" \d$", "", regex=True), as_index=False
    ).size()
    fig = px.bar(by_role.sort_values("size", ascending=False), x="Rôle", y="size",
                 color_discrete_sequence=[RED], title="Postes manquants, par profil")
    fig = plotly_base_layout(fig, legend=False)
    fig.update_layout(yaxis_title="Manques")
    st.plotly_chart(fig, width="stretch")
with c2:
    by_antenne = eq[eq["Statut"] == "MANQUE"].groupby("Antenne", as_index=False).size()
    fig = px.bar(by_antenne.sort_values("size", ascending=False), x="Antenne", y="size",
                 color_discrete_sequence=[BLUE], title="Postes manquants, par antenne")
    fig = plotly_base_layout(fig, legend=False)
    fig.update_layout(yaxis_title="Manques")
    st.plotly_chart(fig, width="stretch")

st.write("")
section_title("PERSONNEL NON AFFECTÉ À UNE ÉQUIPE")
unassigned = unassigned_effectif
if unassigned is not None and not unassigned.empty:
    c1, c2 = st.columns([2, 1])
    with c1:
        st.dataframe(unassigned, width="stretch", hide_index=True, height=380)
    with c2:
        if "Profil" in unassigned.columns:
            fig = px.pie(unassigned, names="Profil", hole=0.35, color_discrete_sequence=CATEGORICAL,
                         title="Profils disponibles")
            fig = plotly_base_layout(fig, height=320)
            st.plotly_chart(fig, width="stretch")
else:
    st.info("Aucun personnel non affecté trouvé dans ce classeur.")

render_sidebar_footer(data.generated_on)
