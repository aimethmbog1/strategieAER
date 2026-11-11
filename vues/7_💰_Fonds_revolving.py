from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from utils.data import NAVY, BLUE, GOLD, RED, GREEN, AMBER, CATEGORICAL
from utils.ui import PAGE_ICON, inject_base_style, section_title, plotly_base_layout, kpi_row, render_sidebar_footer
from utils.loader import get_data
from utils.revolving import (
    staff_table, regions, commercial_zones, agents_for,
    get_register, set_register, next_dossier_id, with_derived_columns,
    REGISTER_COLUMNS, STATUTS, FRAIS_INITIAL_REFERENCE_FCFA, DUREE_REMBOURSEMENT_REFERENCE_ANS,
)

st.set_page_config(page_title="Fonds revolving — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()

data = get_data()  # gardé pour la cohérence de navigation ; non requis sur cette page
st.title("💰 Fonds revolving — Composante 3 du PERACE")
st.caption("Aide au financement des frais de raccordement des ménages — Projet d'Électricité Rurale pour "
           "les Régions Sous-Desservies (PERACE), P163881, crédit IDA / Banque mondiale.")

with st.expander("ℹ️ Ce que cette page représente exactement — à lire avant de l'utiliser", expanded=False):
    st.markdown(
        """
Le classeur Excel du tableau de bord (parc solaire + équipes terrain) **ne contient aucune donnée
sur ce fonds** : il s'agit d'un mécanisme distinct, documenté publiquement par la Banque mondiale, qui
finance les **frais initiaux de branchement des ménages** dans les localités raccordées au réseau
électrique (extension réseau ENEO), et non les sites solaires isolés traités ailleurs dans l'application.

**Ce qui est réel dans cette page :**
- La répartition du **personnel de suivi** (délégations régionales / commerciales, noms) — donnée que
  vous avez fournie.
- Les valeurs de référence documentées pour ce fonds : frais initial de **2 000 FCFA** payé par le
  ménage, remboursement du solde étalé sur **6 à 8 ans**, fonds capitalisé à hauteur de 25 M$ (crédit
  IDA), géré par l'AER — d'après le document de projet de la Banque mondiale et ses rapports de suivi.

**Ce que cette page n'est PAS :**
- Un accès aux vrais dossiers de raccordement ni aux vrais montants décaissés/remboursés — ces données
  ne sont pas publiques et ne sont pas dans le classeur fourni. Le **registre ci-dessous démarre vide** :
  c'est un outil de saisie et de suivi que vous alimentez vous-même, dossier par dossier.
- Une base de données persistante : Streamlit ne conserve pas les données entre deux sessions ou après
  un redéploiement. **Téléchargez régulièrement votre registre en CSV** et rechargez-le à l'ouverture
  d'une nouvelle session pour ne rien perdre.
- Une page géographiquement liée à la carte d'électrification solaire : les « délégations régionales »
  ENEO/AER de ce fonds (DCUD, DCUY, DRC, DRE, DRNEA, DRONO, DRSANO, DRSM, DRSOM) sont un découpage
  commercial différent des 9 « antennes » du réseau solaire — les deux ne sont pas superposées ici,
  pour les mêmes raisons de cohérence des données que sur la page Carte.
        """
    )

st.write("")

# =====================================================================
# Personnel de suivi
# =====================================================================
section_title("PERSONNEL DE SUIVI DU FONDS — RÉPARTITION PAR DÉLÉGATION")
staff = staff_table()

fc1, fc2, fc3 = st.columns(3)
f_region = fc1.multiselect("Délégation régionale", regions(), default=[])
f_zone = fc2.multiselect("Délégation commerciale", sorted(staff["Délégation commerciale"].unique()), default=[])
f_agent_search = fc3.text_input("Rechercher un agent")

staff_view = staff.copy()
if f_region:
    staff_view = staff_view[staff_view["Délégation régionale"].isin(f_region)]
if f_zone:
    staff_view = staff_view[staff_view["Délégation commerciale"].isin(f_zone)]
if f_agent_search:
    staff_view = staff_view[staff_view["Agent"].str.contains(f_agent_search, case=False, na=False)]

kpi_row([
    ("Délégations régionales", str(staff["Délégation régionale"].nunique()), None),
    ("Zones commerciales", str(staff["Délégation commerciale"].nunique()), None),
    ("Agents de suivi", str(staff["Agent"].nunique()), None),
    ("Agents affichés (filtre)", str(len(staff_view)), None),
])

sc1, sc2 = st.columns([1.3, 1])
with sc1:
    st.dataframe(staff_view, width="stretch", hide_index=True, height=420)
    st.download_button("⬇️ Télécharger la liste du personnel (CSV)",
                        staff.to_csv(index=False).encode("utf-8"),
                        "personnel_fonds_revolving.csv", "text/csv")
with sc2:
    by_region = staff.groupby("Délégation régionale", as_index=False)["Agent"].count()
    by_region.columns = ["Délégation régionale", "Nombre d'agents"]
    fig = px.bar(by_region.sort_values("Nombre d'agents", ascending=False),
                 x="Délégation régionale", y="Nombre d'agents", color_discrete_sequence=[NAVY],
                 title="Effectif de suivi par délégation régionale")
    fig = plotly_base_layout(fig, legend=False, height=420)
    st.plotly_chart(fig, width="stretch")

st.write("")

# =====================================================================
# Registre des dossiers de raccordement
# =====================================================================
section_title("REGISTRE DES DOSSIERS DE RACCORDEMENT")

lc, rc = st.columns([1, 1])
with lc:
    uploaded_reg = st.file_uploader("📤 Charger un registre existant (CSV)", type=["csv"], key="reg_upload")
    if uploaded_reg is not None:
        try:
            loaded = pd.read_csv(uploaded_reg)
            loaded = loaded.reindex(columns=REGISTER_COLUMNS)
            loaded["Date d'enregistrement"] = pd.to_datetime(loaded["Date d'enregistrement"], errors="coerce")
            for c in ["Coût total du raccordement (FCFA)", "Frais initial payé par le ménage (FCFA)",
                      "Durée de remboursement (ans)", "Montant remboursé à ce jour (FCFA)"]:
                loaded[c] = pd.to_numeric(loaded[c], errors="coerce")
            if st.button("Remplacer le registre courant par ce fichier"):
                set_register(loaded)
                st.success(f"{len(loaded)} dossier(s) chargé(s).")
                st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Fichier illisible : {exc}")
with rc:
    st.caption("Aucune donnée n'est perdue tant que vous téléchargez votre registre avant de fermer "
               "la session — il n'y a pas de sauvegarde automatique côté serveur dans cet environnement.")

st.markdown("**➕ Ajouter un dossier**")
with st.container(border=True):
    ac1, ac2, ac3 = st.columns(3)
    a_region = ac1.selectbox("Délégation régionale", regions(), key="add_region")
    a_zone = ac2.selectbox("Délégation commerciale", commercial_zones(a_region), key="add_zone")
    zone_agents = agents_for(a_region, a_zone)
    a_agent = ac3.selectbox("Agent en charge", zone_agents, key="add_agent")

    bc1, bc2, bc3, bc4 = st.columns(4)
    a_locality = bc1.text_input("Localité / site", key="add_locality")
    a_date = bc2.date_input("Date d'enregistrement", value=date.today(), key="add_date")
    a_duree = bc3.selectbox("Durée de remboursement (ans)", DUREE_REMBOURSEMENT_REFERENCE_ANS, key="add_duree")
    a_statut = bc4.selectbox("Statut", STATUTS, key="add_statut")

    cc1, cc2, cc3 = st.columns(3)
    a_cout = cc1.number_input("Coût total du raccordement (FCFA)", min_value=0, step=1000, key="add_cout")
    a_initial = cc2.number_input("Frais initial payé par le ménage (FCFA)",
                                  min_value=0, step=100, value=FRAIS_INITIAL_REFERENCE_FCFA, key="add_initial")
    a_rembourse = cc3.number_input("Montant remboursé à ce jour (FCFA)", min_value=0, step=1000, key="add_rembourse")

    a_notes = st.text_area("Notes", key="add_notes", height=68)

    if st.button("Ajouter au registre", type="primary"):
        if not a_locality:
            st.warning("Renseignez au moins la localité / le site avant d'ajouter le dossier.")
        else:
            reg = get_register()
            new_row = pd.DataFrame([{
                "N° dossier": next_dossier_id(reg),
                "Date d'enregistrement": pd.to_datetime(a_date),
                "Délégation régionale": a_region,
                "Délégation commerciale": a_zone,
                "Agent en charge": a_agent,
                "Localité / site": a_locality,
                "Coût total du raccordement (FCFA)": a_cout,
                "Frais initial payé par le ménage (FCFA)": a_initial,
                "Durée de remboursement (ans)": a_duree,
                "Montant remboursé à ce jour (FCFA)": a_rembourse,
                "Statut": a_statut,
                "Notes": a_notes,
            }])
            set_register(pd.concat([reg, new_row], ignore_index=True))
            st.success(f"Dossier ajouté pour « {a_locality} ».")
            st.rerun()

st.write("")
st.markdown("**📋 Dossiers enregistrés — modifiables directement dans le tableau**")
register = get_register()

if register.empty:
    st.info("Aucun dossier enregistré pour l'instant. Utilisez le formulaire ci-dessus, ou chargez un "
            "registre CSV précédemment téléchargé.")
else:
    edited = st.data_editor(
        register,
        width="stretch",
        hide_index=True,
        num_rows="dynamic",
        height=min(60 + 36 * (len(register) + 1), 480),
        column_config={
            "Date d'enregistrement": st.column_config.DateColumn("Date d'enregistrement"),
            "Statut": st.column_config.SelectboxColumn("Statut", options=STATUTS),
            "Délégation régionale": st.column_config.SelectboxColumn("Délégation régionale", options=regions()),
            "Coût total du raccordement (FCFA)": st.column_config.NumberColumn(
                "Coût total du raccordement (FCFA)", min_value=0, step=1000, format="%d"),
            "Frais initial payé par le ménage (FCFA)": st.column_config.NumberColumn(
                "Frais initial payé (FCFA)", min_value=0, step=100, format="%d"),
            "Durée de remboursement (ans)": st.column_config.NumberColumn(
                "Durée remb. (ans)", min_value=1, max_value=15, step=1),
            "Montant remboursé à ce jour (FCFA)": st.column_config.NumberColumn(
                "Remboursé à ce jour (FCFA)", min_value=0, step=1000, format="%d"),
        },
        key="register_editor",
    )
    set_register(edited)
    register = edited

    st.download_button("⬇️ Télécharger le registre (CSV)",
                        register.to_csv(index=False).encode("utf-8"),
                        f"registre_fonds_revolving_{date.today().isoformat()}.csv", "text/csv")

st.write("")

# =====================================================================
# Indicateurs & analyse — calculés uniquement à partir des dossiers saisis
# =====================================================================
section_title("INDICATEURS DU FONDS — CALCULÉS À PARTIR DES DOSSIERS SAISIS CI-DESSUS")
view = with_derived_columns(register)

if view.empty:
    st.info("Les indicateurs apparaîtront ici dès qu'au moins un dossier sera saisi.")
else:
    total_cout = view["Coût total du raccordement (FCFA)"].sum()
    total_a_rembourser = view["Montant à rembourser (FCFA)"].sum()
    total_rembourse = view["Montant remboursé à ce jour (FCFA)"].sum()
    total_solde = view["Solde restant dû (FCFA)"].sum()
    taux_global = (total_rembourse / total_a_rembourser * 100) if total_a_rembourser else 0

    kpi_row([
        ("Dossiers", str(len(view)), None),
        ("Total engagé (FCFA)", f"{total_cout:,.0f}".replace(",", " "), None),
        ("Total remboursé (FCFA)", f"{total_rembourse:,.0f}".replace(",", " "), None),
        ("Solde restant dû (FCFA)", f"{total_solde:,.0f}".replace(",", " "), None),
        ("Taux de recouvrement", f"{taux_global:,.1f} %", None),
    ])

    ic1, ic2 = st.columns(2)
    with ic1:
        by_region = view.groupby("Délégation régionale", as_index=False)[
            ["Montant à rembourser (FCFA)", "Montant remboursé à ce jour (FCFA)"]].sum()
        fig = go.Figure()
        fig.add_bar(name="À rembourser", x=by_region["Délégation régionale"],
                    y=by_region["Montant à rembourser (FCFA)"], marker_color=BLUE)
        fig.add_bar(name="Remboursé", x=by_region["Délégation régionale"],
                    y=by_region["Montant remboursé à ce jour (FCFA)"], marker_color=GREEN)
        fig.update_layout(barmode="group", title="Engagé vs remboursé, par délégation régionale")
        fig = plotly_base_layout(fig)
        st.plotly_chart(fig, width="stretch")
    with ic2:
        counts = view["Statut"].value_counts()
        colors_map = {"En cours": BLUE, "Soldé": GREEN, "En retard": AMBER, "Litige": RED}
        fig = go.Figure(data=[go.Pie(
            labels=counts.index, values=counts.values, hole=0.45,
            marker=dict(colors=[colors_map.get(s, "#8A8A8A") for s in counts.index]),
            textinfo="label+percent",
        )])
        fig.update_layout(title="Répartition des dossiers par statut")
        fig = plotly_base_layout(fig, legend=False)
        st.plotly_chart(fig, width="stretch")

    st.markdown("**Charge par agent** — dossiers suivis et solde restant dû")
    by_agent = view.groupby("Agent en charge", as_index=False).agg(
        Dossiers=("N° dossier", "count"),
        **{"Solde restant dû (FCFA)": ("Solde restant dû (FCFA)", "sum")},
    ).sort_values("Solde restant dû (FCFA)", ascending=False)
    st.dataframe(by_agent, width="stretch", hide_index=True)

    with st.expander("📄 Détail des dossiers avec montants calculés"):
        st.dataframe(view, width="stretch", hide_index=True, height=400)

render_sidebar_footer(data.generated_on if data else "")
