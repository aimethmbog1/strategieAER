from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from utils.data import NAVY, BLUE, GOLD, RED, GREEN, AMBER, CATEGORICAL
from utils.ui import PAGE_ICON, inject_base_style, section_title, plotly_base_layout, kpi_row, render_sidebar_footer
from utils.loader import get_data
from utils.projets import (
    REGISTER_COLUMNS, STATUTS_PROJET, MOTIFS_BLOCAGE_OPTIONS, MOTIF_NON_RENSEIGNE, REGIONS_PRIORITAIRES,
    empty_register, get_register, set_register, next_projet_id, site_lookup, with_derived_columns,
)

st.set_page_config(page_title="Suivi de projets — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()

data = get_data()
if data is None:
    st.stop()

st.title("📌 Suivi de l'avancement des projets d'électrification")
st.caption("Réactivité des agents, suivi des projets en cours, reprise des projets à l'arrêt, relance NOSO / "
           "Extrême-Nord — registre à alimenter, rattaché aux 499 sites réels du parc solaire.")

with st.expander("ℹ️ Ce que cette page représente exactement — à lire avant de l'utiliser", expanded=False):
    st.markdown(
        """
Le classeur Excel du tableau de bord (parc solaire + équipes terrain) **ne contient aucune donnée
d'avancement de projet** : seulement une photo de capacité (sites installés, puissance, personnel). Le
statut « en cours / suspendu / repris / terminé » d'un projet n'existe dans aucune feuille — cette page
comble ce manque avec un **registre à alimenter**, sur le même principe que le Fonds revolving.

**Ce qui est réel ici :**
- Le rattachement de chaque ligne à un **site réel** parmi les 499 sites du parc solaire — Région, Antenne
  proposée et Phase sont recopiées automatiquement depuis la feuille « Données sites », jamais ressaisies à
  la main, pour éviter toute incohérence avec le reste de l'application.
- Le marqueur **« région prioritaire »** (NOSO = Nord-Ouest + Sud-Ouest, + Extrême-Nord) est calculé à
  partir de la région réelle du site choisi.

**Ce que cette page n'est PAS :**
- Un accès à un suivi déjà existant ailleurs — le **registre démarre vide**. Tant qu'aucune ligne n'est
  saisie, l'absence d'alerte ne veut pas dire « tout va bien », seulement « rien n'a encore été renseigné ».
- Une base de données persistante : comme pour le Fonds revolving et les Statistiques de compteurs,
  Streamlit ne conserve rien entre deux sessions. **Téléchargez le registre en CSV avant de fermer**, et
  rechargez-le à l'ouverture suivante.
        """
    )

sites = data.sites
lookup = site_lookup(sites)
if lookup.empty:
    st.warning("Feuille « Données sites » introuvable ou vide — impossible de rattacher des projets à des "
               "sites réels tant que le classeur AER n'est pas chargé.")
    st.stop()

st.write("")

# =====================================================================
# Ajout d'une ligne au registre
# =====================================================================
section_title("➕ AJOUTER UN PROJET AU SUIVI")
with st.container(border=True):
    site_names = sorted(lookup["Nom du site"].dropna().unique())
    a1, a2, a3 = st.columns([2, 1, 1])
    a_site = a1.selectbox("Site (parc solaire réel)", site_names, index=None,
                           placeholder="Choisir un site…", key="prj_add_site")
    a_statut = a2.selectbox("Statut", STATUTS_PROJET, key="prj_add_statut")
    a_date = a3.date_input("Date de dernier mouvement", value=date.today(), key="prj_add_date")

    if a_site:
        site_row = lookup[lookup["Nom du site"] == a_site].iloc[0]
        st.caption(f"Région : **{site_row.get('Région', '—')}** · Antenne : **{site_row.get('Antenne proposée', '—')}** "
                   f"· Phase : **{site_row.get('Phase', '—')}**"
                   + (" · 🔶 région prioritaire (NOSO / Extrême-Nord)" if site_row.get("Région") in REGIONS_PRIORITAIRES else ""))

    b1, b2 = st.columns(2)
    a_motif = b1.selectbox("Motif de blocage (si suspendu / à relancer)", MOTIFS_BLOCAGE_OPTIONS,
                            key="prj_add_motif")
    a_resp = b2.text_input("Responsable désigné", key="prj_add_resp")
    a_notes = st.text_area("Notes", key="prj_add_notes", height=68)

    if st.button("Ajouter au suivi", type="primary", key="prj_add_btn"):
        if not a_site:
            st.warning("Choisissez un site avant d'ajouter la ligne.")
        else:
            site_row = lookup[lookup["Nom du site"] == a_site].iloc[0]
            reg = get_register()
            new_row = pd.DataFrame([{
                "N° projet": next_projet_id(reg),
                "Site": a_site,
                "Région": site_row.get("Région"),
                "Antenne proposée": site_row.get("Antenne proposée"),
                "Phase": site_row.get("Phase"),
                "Statut": a_statut,
                "Date de dernier mouvement": pd.to_datetime(a_date),
                "Motif de blocage": a_motif,
                "Responsable désigné": a_resp,
                "Notes": a_notes,
            }])
            set_register(pd.concat([reg, new_row], ignore_index=True))
            st.success(f"Projet ajouté pour « {a_site} ».")
            st.rerun()

st.write("")

# =====================================================================
# Chargement d'un registre existant
# =====================================================================
with st.expander("📤 Charger un registre existant (CSV)"):
    uploaded_reg = st.file_uploader("Fichier CSV précédemment téléchargé", type=["csv"], key="prj_upload")
    if uploaded_reg is not None:
        try:
            loaded = pd.read_csv(uploaded_reg)
            loaded = loaded.reindex(columns=REGISTER_COLUMNS)
            loaded["Date de dernier mouvement"] = pd.to_datetime(loaded["Date de dernier mouvement"], errors="coerce")
            if st.button("Remplacer le registre courant par ce fichier", key="prj_replace_btn"):
                set_register(loaded)
                st.success(f"{len(loaded)} projet(s) chargé(s).")
                st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Fichier illisible : {exc}")

st.write("")

# =====================================================================
# Registre — tableau éditable
# =====================================================================
section_title("📋 PROJETS SUIVIS — MODIFIABLES DIRECTEMENT DANS LE TABLEAU")
register = get_register()

if register.empty:
    st.info("Aucun projet suivi pour l'instant. Utilisez le formulaire ci-dessus, ou chargez un registre CSV "
            "précédemment téléchargé.")
else:
    edited = st.data_editor(
        register,
        width="stretch",
        hide_index=True,
        num_rows="dynamic",
        height=min(60 + 36 * (len(register) + 1), 480),
        column_config={
            "Date de dernier mouvement": st.column_config.DateColumn("Date de dernier mouvement"),
            "Statut": st.column_config.SelectboxColumn("Statut", options=STATUTS_PROJET),
            "Motif de blocage": st.column_config.SelectboxColumn(
                "Motif de blocage", options=MOTIFS_BLOCAGE_OPTIONS),
        },
        key="projets_editor",
    )
    set_register(edited)
    register = edited

    st.download_button("⬇️ Télécharger le registre (CSV)",
                        register.to_csv(index=False).encode("utf-8"),
                        f"registre_suivi_projets_{date.today().isoformat()}.csv", "text/csv")

st.write("")

# =====================================================================
# Indicateurs & priorisation — calculés uniquement à partir des lignes saisies
# =====================================================================
section_title("INDICATEURS — CALCULÉS À PARTIR DES PROJETS SAISIS CI-DESSUS")
view = with_derived_columns(register)

if view.empty:
    st.info("Les indicateurs, le plan de reprise et les alertes « région prioritaire » apparaîtront ici dès "
            "qu'au moins un projet sera saisi.")
else:
    n_total = len(view)
    n_suspendu = int((view["Statut"] == "Suspendu").sum())
    n_en_cours = int((view["Statut"] == "En cours").sum())
    n_prioritaire = int((view["Région prioritaire (NOSO / Extrême-Nord)"] == "Oui").sum())
    n_prioritaire_bloque = int(((view["Région prioritaire (NOSO / Extrême-Nord)"] == "Oui") &
                                 (view["Statut"].isin(["Planifié", "Suspendu"]))).sum())

    kpi_row([
        ("Projets suivis", str(n_total), None),
        ("En cours", str(n_en_cours), None),
        ("Suspendus", str(n_suspendu), None),
        ("En région prioritaire (NOSO / Extrême-Nord)", str(n_prioritaire), None),
        ("Prioritaires à relancer", str(n_prioritaire_bloque), None),
    ])

    ic1, ic2 = st.columns(2)
    with ic1:
        counts = view["Statut"].value_counts().reindex(STATUTS_PROJET).fillna(0)
        colors_map = {"Planifié": GOLD, "En cours": BLUE, "Suspendu": RED, "Repris": AMBER, "Terminé": GREEN}
        fig = go.Figure(data=[go.Pie(
            labels=counts.index, values=counts.values, hole=0.45,
            marker=dict(colors=[colors_map.get(s, "#8A8A8A") for s in counts.index]),
            textinfo="label+percent", sort=False,
        )])
        fig.update_layout(title="Répartition des projets par statut")
        fig = plotly_base_layout(fig, legend=False)
        st.plotly_chart(fig, width="stretch")
    with ic2:
        by_region = view.groupby("Région", as_index=False).size().sort_values("size", ascending=False)
        by_region["Prioritaire"] = by_region["Région"].isin(REGIONS_PRIORITAIRES)
        fig = px.bar(by_region, x="Région", y="size", color="Prioritaire",
                     color_discrete_map={True: RED, False: NAVY},
                     title="Projets suivis par région (rouge = NOSO / Extrême-Nord)")
        fig = plotly_base_layout(fig, legend=False)
        fig.update_layout(yaxis_title="Projets")
        st.plotly_chart(fig, width="stretch")

    st.write("")
    section_title("🚨 PLAN DE REPRISE / RELANCE PRIORITAIRE")
    st.caption("Projets suspendus ou planifiés, triés par ancienneté du dernier mouvement — et toujours "
               "en tête les régions prioritaires (NOSO / Extrême-Nord).")
    a_relancer = view[view["Statut"].isin(["Planifié", "Suspendu"])].copy()
    if a_relancer.empty:
        st.success("Aucun projet suspendu ou planifié en attente — rien à relancer pour l'instant selon le registre.")
    else:
        a_relancer["_tri_prioritaire"] = a_relancer["Région prioritaire (NOSO / Extrême-Nord)"] == "Oui"
        a_relancer = a_relancer.sort_values(
            ["_tri_prioritaire", "Jours depuis dernier mouvement"], ascending=[False, False]
        )
        cols_show = ["N° projet", "Site", "Région", "Antenne proposée", "Statut",
                      "Jours depuis dernier mouvement", "Région prioritaire (NOSO / Extrême-Nord)",
                      "Motif de blocage", "Responsable désigné"]
        st.dataframe(a_relancer[cols_show], width="stretch", hide_index=True, height=360)
        st.download_button("⬇️ Télécharger ce plan de reprise (CSV)",
                            a_relancer[cols_show].to_csv(index=False).encode("utf-8"),
                            "plan_reprise_relance.csv", "text/csv", key="prj_dl_plan")

    with st.expander("📄 Détail complet du registre (avec colonnes calculées)"):
        st.dataframe(view, width="stretch", hide_index=True, height=400)

render_sidebar_footer(data.generated_on if data else "")
