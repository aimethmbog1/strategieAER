from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from utils.data import NAVY, BLUE, GOLD, RED, GREEN, AMBER, GREY, CATEGORICAL
from utils.loader import get_data
from utils.ui import PAGE_ICON, inject_base_style, section_title, plotly_base_layout, kpi_row, render_sidebar_footer
from utils.compteurs import (
    read_excel_sheet_names, load_excel,
    est_format_holley, parse_date_from_filename, build_from_holley_files,
    apply_column_mapping, locality_cleanup_ui, lot_summary, load_official_sites,
    default_phases, assign_phases, cache_dataframe,
)

st.set_page_config(page_title="Statistiques des compteurs — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()

data = get_data()  # gardé pour la cohérence de navigation ; non requis sur cette page
st.title("🔌 Statistiques des compteurs")
st.caption("Compteurs (abonnés) installés — répartition par localité et par période d'installation, à partir "
           "des exports du système de gestion des compteurs prépayés « Holley ».")

with st.expander("ℹ️ Ce que cette page représente exactement — à lire avant de l'utiliser", expanded=False):
    st.markdown(
        """
Le classeur Excel du tableau de bord (parc solaire + équipes terrain) **ne contient aucune donnée sur les
compteurs/abonnés installés** : cette page lit ses **propres fichiers**, déposés indépendamment ci-contre,
et les garde en mémoire pour la durée de la session — comme le registre du Fonds revolving.

**Format reconnu automatiquement — export « Holley » :**
- Détecté par la présence des colonnes `Full Address` / `Template Code`.
- La colonne `Opening Date` de ces exports est un **champ système figé à 01/01/2018** sur tous les fichiers
  observés : elle n'indique donc **pas** la vraie date d'installation.
- Chaque fichier correspond en réalité à un **lot d'abonnés** exporté à une date donnée, et c'est **la date
  présente dans le nom du fichier** (ex. `01-10-2024.xls`) qui sert de période d'installation pour toutes ses
  lignes — convention confirmée pour ces fichiers. Cette date est affichée et modifiable ci-contre avant de
  lancer les statistiques, et le détail par lot reste consultable dans l'onglet « Vue d'ensemble ».
- Si un fichier ne correspond pas à ce format, une correspondance manuelle des colonnes est proposée (un
  fichier à la fois).

**Qualité des données :** les noms de localités contiennent souvent des variantes d'orthographe (coquilles,
casse, espaces superflus). Un regroupement automatique est **suggéré** (par similarité de texte) dans la
barre latérale, mais rien n'est fusionné sans validation — modifie la proposition si besoin.

**Persistance :** comme pour le Fonds revolving, Streamlit ne conserve rien entre deux sessions — les
fichiers déposés ici sont à re-déposer à chaque ouverture. Les tableaux de cette page s'exportent en CSV.
        """
    )

# =============================================================================
# Barre latérale — dépôt des fichiers
# =============================================================================
st.sidebar.markdown("### 📥 Données compteurs")
jour_mois_annee = st.sidebar.toggle(
    "Dates de fichier au format JJ-MM-AAAA", value=True, key="cpt_jma",
    help="Le nom de chaque fichier doit contenir une date (ex. 01-10-2024.xls), qui sert de période "
         "d'installation pour toutes ses lignes. Désactive si tes fichiers sont nommés MM-JJ-AAAA.",
)
uploaded_files = st.sidebar.file_uploader(
    "Fichiers Excel des abonnés installés", type=["xlsx", "xls"], accept_multiple_files=True, key="cpt_upload",
    help="Dépose un ou plusieurs fichiers — le format export Holley (colonnes Full Address / Template Code) "
         "est reconnu automatiquement.",
)

df = None
if uploaded_files:
    lus, erreurs = [], []
    for uf in uploaded_files:
        try:
            feuilles = read_excel_sheet_names(uf)
            raw = load_excel(uf, sheet_name=feuilles[0] if feuilles else 0)
        except Exception as e:  # noqa: BLE001
            erreurs.append(f"{uf.name} : {e}")
            continue
        lus.append({"nom": uf.name, "df": raw})
    for e in erreurs:
        st.sidebar.error(e)

    df_brut = None
    if lus:
        if all(est_format_holley(l["df"]) for l in lus):
            st.sidebar.markdown("**Période de chaque lot** (détectée depuis le nom du fichier — à corriger si besoin)")
            fichiers_avec_periode = []
            for l in lus:
                devinee = parse_date_from_filename(l["nom"], jour_mois_annee) or date.today()
                choisie = st.sidebar.date_input(l["nom"], value=devinee, key=f"cpt_periode_{l['nom']}")
                fichiers_avec_periode.append({"nom": l["nom"], "df": l["df"], "periode": choisie})
            df_brut = build_from_holley_files(fichiers_avec_periode)
            st.sidebar.success(f"{len(df_brut)} lignes chargées depuis {len(lus)} fichier(s) — format Holley détecté.")
        elif len(lus) == 1:
            brut = lus[0]["df"]
            st.sidebar.markdown("**Correspondance des colonnes** (format non reconnu automatiquement)")
            colonnes = list(brut.columns)
            col_localite = st.sidebar.selectbox("Colonne → Localité", colonnes, key="cpt_map_localite")
            col_date = st.sidebar.selectbox("Colonne → Date d'installation", colonnes, key="cpt_map_date")
            col_poste = st.sidebar.selectbox("Colonne → Poste (optionnel)", ["(aucune)"] + colonnes, key="cpt_map_poste")
            col_type = st.sidebar.selectbox("Colonne → Type de compteur (optionnel)", ["(aucune)"] + colonnes, key="cpt_map_type")
            mapping = {
                "localite": col_localite, "date_installation": col_date,
                "poste": None if col_poste == "(aucune)" else col_poste,
                "type_compteur": None if col_type == "(aucune)" else col_type,
            }
            df_brut, n_rejetees = apply_column_mapping(brut, mapping)
            st.sidebar.success(f"{len(df_brut)} lignes chargées.")
            if n_rejetees:
                st.sidebar.warning(f"{n_rejetees} ligne(s) ignorée(s) (date d'installation illisible).")
        else:
            st.sidebar.warning(
                "Plusieurs fichiers chargés mais tous ne correspondent pas au format Holley reconnu "
                "automatiquement — dépose-les un par un pour une correspondance manuelle des colonnes."
            )

    if df_brut is not None and not df_brut.empty:
        df = locality_cleanup_ui(df_brut)

if df is None:
    st.sidebar.info(
        "Aucun fichier chargé — cette page démarre **vide, sans aucune donnée fictive**. Dépose tes "
        "fichiers Excel ci-dessus pour voir tes vraies statistiques de compteurs."
    )
    st.info(
        "Aucune donnée de compteurs pour l'instant. En attendant, voici les **localités officielles du "
        "parc solaire AER** que cette page reconnaît et vers lesquelles elle corrige automatiquement "
        "les noms détectés dans tes fichiers Holley — aucune n'a encore de compteur installé ici."
    )
    sites_ref = load_official_sites()
    if not sites_ref.empty:
        st.write("")
        section_title(f"{len(sites_ref)} LOCALITÉS OFFICIELLES DU PARC SOLAIRE AER, PAR RÉGION")
        renommage = {"nom": "Localité", "region": "Région", "departement": "Département", "antenne": "Antenne"}
        colonnes_aff = [c for c in ["nom", "region", "departement", "antenne"] if c in sites_ref.columns]
        affichage_ref = sites_ref[colonnes_aff].rename(columns=renommage)
        tri = [c for c in ["Région", "Localité"] if c in affichage_ref.columns]
        affichage_ref = affichage_ref.sort_values(tri) if tri else affichage_ref
        st.dataframe(affichage_ref, width="stretch", hide_index=True, height=450)
    st.stop()

if df.empty:
    st.info("Aucune donnée à afficher.")
    st.stop()

# =============================================================================
# Barre latérale — phases du projet (aucune colonne « phase » n'existe dans
# les exports Holley : les plages de dates sont définies et ajustées ici)
# =============================================================================
st.sidebar.markdown("### 🏗️ Phases du projet")
if "cpt_phases_df" not in st.session_state:
    st.session_state["cpt_phases_df"] = default_phases(df)
with st.sidebar.expander("Définir les phases (dates éditables)", expanded=False):
    st.caption(
        "Chaque compteur est classé dans la phase dont la plage de dates couvre sa période "
        "d'installation. Les plages ci-dessous sont un point de départ (3 tiers égaux) — "
        "corrige-les avec les vraies dates de chaque phase du projet, ajoute ou supprime des lignes."
    )
    phases_editees = st.data_editor(
        st.session_state["cpt_phases_df"], num_rows="dynamic", hide_index=True, width="stretch",
        column_config={
            "Phase": st.column_config.TextColumn("Phase", required=True),
            "Début": st.column_config.DateColumn("Début", format="DD/MM/YYYY"),
            "Fin": st.column_config.DateColumn("Fin", format="DD/MM/YYYY"),
        },
        key="cpt_phases_editor",
    )
    st.session_state["cpt_phases_df"] = phases_editees
df["phase"] = assign_phases(df, phases_editees)
cache_dataframe(df)  # pour le résumé de la page d'accueil — voir utils/compteurs.py

# =============================================================================
# KPI globaux
# =============================================================================
total = len(df)
nb_localites = df["localite"].nunique()
nb_postes = df["poste"].nunique() if "poste" in df else None
derniere_periode = df["periode"].max()
nb_solaire = int(df["solaire"].sum()) if "solaire" in df else 0
taux_solaire = f"{nb_solaire / total * 100:.0f} %" if total else "—"

kpi_row([
    ("🔌 Compteurs installés", f"{total:,}".replace(",", " "), None),
    ("📍 Localités couvertes", f"{nb_localites}", None),
    ("🗺️ Postes couverts", f"{nb_postes}" if nb_postes else "—", None),
    ("📅 Dernière période", derniere_periode.strftime("%m/%Y") if pd.notna(derniere_periode) else "—", None),
    ("☀️ Compteurs solaires", taux_solaire, None),
])

st.write("")

tab_vue, tab_localite, tab_periode, tab_croisement, tab_phase = st.tabs([
    "📊 Vue d'ensemble", "📍 Par localité", "📅 Par période", "🧭 Localité × période", "🏗️ Par phase",
])

# -----------------------------------------------------------------------
# Vue d'ensemble
# -----------------------------------------------------------------------
with tab_vue:
    section_title("TOP 10 DES LOCALITÉS")
    top10 = df["localite"].value_counts().head(10).reset_index()
    top10.columns = ["Localité", "Compteurs installés"]
    fig = px.bar(top10.sort_values("Compteurs installés"), x="Compteurs installés", y="Localité",
                 orientation="h", color_discrete_sequence=[NAVY])
    fig = plotly_base_layout(fig, height=360, legend=False)
    st.plotly_chart(fig, width="stretch")

    section_title("RYTHME D'INSTALLATION — PÉRIODES LES PLUS RÉCENTES")
    par_periode_apercu = df.groupby("periode").size().reset_index(name="Installations")
    par_periode_apercu = par_periode_apercu.sort_values("periode").tail(12)
    fig2 = px.bar(par_periode_apercu, x="periode", y="Installations", color_discrete_sequence=[BLUE])
    fig2 = plotly_base_layout(fig2, height=300, legend=False)
    fig2.update_xaxes(title=None)
    st.plotly_chart(fig2, width="stretch")

    if "nom_fichier" in df.columns and df["nom_fichier"].nunique() > 0:
        section_title("TRAÇABILITÉ PAR LOT — UN FICHIER DÉPOSÉ = UN LOT D'ABONNÉS")
        st.caption("Vérifie ici que la période détectée depuis le nom de chaque fichier est cohérente avec "
                   "le lot qu'il contient.")
        resume_lots = lot_summary(df)
        st.dataframe(
            resume_lots, width="stretch", hide_index=True,
            column_config={"Période": st.column_config.DateColumn("Période", format="MM/YYYY")},
        )

# -----------------------------------------------------------------------
# Par localité
# -----------------------------------------------------------------------
with tab_localite:
    df_loc = df
    if "poste" in df_loc and df_loc["poste"].nunique() > 1:
        postes = sorted(df_loc["poste"].dropna().unique().tolist())
        # La clé inclut la liste des postes : si le jeu de données change (nouveaux fichiers
        # déposés, ou bascule exemple → réel), Streamlit traite le filtre comme un nouveau
        # widget et resélectionne tout par défaut, au lieu de garder une ancienne sélection
        # devenue invalide (qui se traduirait par un filtre vide et silencieux).
        cle_filtre = "cpt_poste_filter_" + str(abs(hash(tuple(postes))))
        choix_postes = st.multiselect("Filtrer par poste", postes, default=postes, key=cle_filtre)
        df_loc = df_loc[df_loc["poste"].isin(choix_postes)]

    if df_loc.empty:
        st.warning("Aucune localité ne correspond au filtre choisi.")
    else:
        par_loc = df_loc["localite"].value_counts().reset_index()
        par_loc.columns = ["Localité", "Compteurs installés"]
        localite_top = par_loc.iloc[0]

        kpi_row([
            ("📍 Localités couvertes", str(df_loc["localite"].nunique()), None),
            ("🥇 Localité la plus équipée", localite_top["Localité"], None),
            (f"🔌 Compteurs à {localite_top['Localité']}", str(int(localite_top["Compteurs installés"])), None),
            ("📊 Compteurs / localité (moy.)", f"{len(df_loc) / df_loc['localite'].nunique():.0f}", None),
        ])

        st.write("")
        section_title("COMPTEURS INSTALLÉS PAR LOCALITÉ")
        NB_AFFICHEES = 15
        if len(par_loc) > NB_AFFICHEES:
            tete = par_loc.head(NB_AFFICHEES)
            reste = par_loc.iloc[NB_AFFICHEES:]["Compteurs installés"].sum()
            affichage = pd.concat([tete, pd.DataFrame([{"Localité": "Autres localités", "Compteurs installés": reste}])])
            st.caption(f"{len(par_loc)} localités au total — les {NB_AFFICHEES} premières sont détaillées, le "
                       "reste est regroupé sous « Autres localités ».")
        else:
            affichage = par_loc
        affichage = affichage.sort_values("Compteurs installés")
        couleurs = [GREY if loc == "Autres localités" else NAVY for loc in affichage["Localité"]]
        fig = px.bar(affichage, x="Compteurs installés", y="Localité", orientation="h", text="Compteurs installés")
        fig.update_traces(marker_color=couleurs, textposition="outside")
        fig = plotly_base_layout(fig, height=max(360, 28 * len(affichage)), legend=False)
        st.plotly_chart(fig, width="stretch")

        if "poste" in df_loc and df_loc["poste"].nunique() > 1:
            section_title("RÉPARTITION PAR POSTE")
            par_poste = df_loc["poste"].value_counts().reset_index()
            par_poste.columns = ["Poste", "Compteurs installés"]
            fig_r = px.bar(par_poste.sort_values("Compteurs installés"), x="Compteurs installés", y="Poste",
                           orientation="h", color_discrete_sequence=[BLUE])
            fig_r = plotly_base_layout(fig_r, height=max(280, 32 * len(par_poste)), legend=False)
            st.plotly_chart(fig_r, width="stretch")

        if "type_compteur" in df_loc and df_loc["type_compteur"].nunique() > 1:
            section_title("RÉPARTITION PAR TYPE DE COMPTEUR")
            par_type = df_loc["type_compteur"].value_counts().reset_index()
            par_type.columns = ["Type de compteur", "Compteurs installés"]
            couleurs_type = [GOLD if ("SOLAR" in t or "SOLAIRE" in t) else BLUE for t in par_type["Type de compteur"]]
            fig_t = px.bar(par_type.sort_values("Compteurs installés"), x="Compteurs installés", y="Type de compteur",
                           orientation="h", text="Compteurs installés")
            fig_t.update_traces(marker_color=couleurs_type, textposition="outside")
            fig_t = plotly_base_layout(fig_t, height=max(220, 40 * len(par_type)), legend=False)
            st.plotly_chart(fig_t, width="stretch")

        st.write("")
        section_title("TABLEAU DÉTAILLÉ")
        tableau = df_loc.groupby("localite").agg(Compteurs=("localite", "size"), Dernière_période=("periode", "max"))
        if "solaire" in df_loc:
            tableau["Compteurs solaires"] = df_loc[df_loc["solaire"]].groupby("localite").size()
            tableau["Compteurs solaires"] = tableau["Compteurs solaires"].fillna(0).astype(int)
        tableau = tableau.sort_values("Compteurs", ascending=False).reset_index()
        tableau.columns = ["Localité"] + list(tableau.columns[1:])
        st.dataframe(
            tableau, width="stretch", hide_index=True,
            column_config={"Dernière_période": st.column_config.DateColumn("Dernière période", format="MM/YYYY")},
        )
        st.download_button("⬇️ Télécharger ce tableau (CSV)", tableau.to_csv(index=False).encode("utf-8"),
                            "compteurs_par_localite.csv", "text/csv", key="cpt_dl_localite")

# -----------------------------------------------------------------------
# Par période
# -----------------------------------------------------------------------
with tab_periode:
    date_min, date_max = df["periode"].min().date(), df["periode"].max().date()
    c1, c2 = st.columns([2, 1])
    with c1:
        if date_min == date_max:
            st.markdown(f"**Période disponible :** {date_min.strftime('%m/%Y')} (un seul lot chargé)")
            debut, fin = date_min, date_max
        else:
            plage = st.date_input("Période à afficher", value=(date_min, date_max),
                                   min_value=date_min, max_value=date_max, key="cpt_plage")
            debut, fin = plage if isinstance(plage, tuple) and len(plage) == 2 else (date_min, date_max)
    with c2:
        granularite = st.radio("Granularité", ["Mois", "Trimestre", "Année"], horizontal=True, index=0, key="cpt_gran")

    masque = (df["periode"].dt.date >= debut) & (df["periode"].dt.date <= fin)
    periode_df = df[masque]

    if periode_df.empty:
        st.warning("Aucune installation sur la période choisie.")
    else:
        code_periode = {"Mois": "M", "Trimestre": "Q", "Année": "Y"}[granularite]
        periode_df = periode_df.copy()
        periode_df["bucket"] = periode_df["periode"].dt.to_period(code_periode).dt.to_timestamp()

        par_bucket = periode_df.groupby("bucket").size().reset_index(name="Nouvelles installations").sort_values("bucket")
        par_bucket["Cumul"] = par_bucket["Nouvelles installations"].cumsum()

        moyenne = par_bucket["Nouvelles installations"].mean()
        meilleure = par_bucket.loc[par_bucket["Nouvelles installations"].idxmax()]
        kpi_row([
            ("🔌 Installations sur la période", f"{len(periode_df):,}".replace(",", " "), None),
            (f"📈 Moyenne par {granularite.lower()}", f"{moyenne:.0f}", None),
            (f"🏆 Meilleur(e) {granularite.lower()}",
             meilleure["bucket"].strftime("%m/%Y") if granularite != "Année" else meilleure["bucket"].strftime("%Y"),
             f"{int(meilleure['Nouvelles installations'])} installations"),
        ])

        st.write("")
        section_title(f"NOUVELLES INSTALLATIONS PAR {granularite.upper()}")
        fig = px.bar(par_bucket, x="bucket", y="Nouvelles installations", color_discrete_sequence=[NAVY])
        fig = plotly_base_layout(fig, height=340, legend=False)
        fig.update_xaxes(title=None)
        st.plotly_chart(fig, width="stretch")

        section_title("CUMUL DES INSTALLATIONS DANS LE TEMPS")
        fig2 = px.line(par_bucket, x="bucket", y="Cumul", markers=True, color_discrete_sequence=[BLUE])
        fig2 = plotly_base_layout(fig2, height=300, legend=False)
        fig2.update_xaxes(title=None)
        fig2.update_traces(line=dict(width=2.5))
        st.plotly_chart(fig2, width="stretch")

        st.write("")
        section_title("TABLEAU DÉTAILLÉ")
        tableau_p = par_bucket.rename(columns={"bucket": "Période"})
        st.dataframe(tableau_p, width="stretch", hide_index=True)
        st.download_button("⬇️ Télécharger ce tableau (CSV)", tableau_p.to_csv(index=False).encode("utf-8"),
                            "compteurs_par_periode.csv", "text/csv", key="cpt_dl_periode")

# -----------------------------------------------------------------------
# Croisement localité × période
# -----------------------------------------------------------------------
with tab_croisement:
    section_title("INSTALLATIONS PAR LOCALITÉ ET PAR PÉRIODE")
    toutes_localites_crois = df["localite"].value_counts().index.tolist()
    vue_croisement = st.radio(
        "Localités affichées",
        [f"Top 12 des localités les plus équipées", f"Toutes les localités ({len(toutes_localites_crois)})"],
        horizontal=True, key="cpt_vue_croisement",
    )
    if vue_croisement.startswith("Top 12"):
        st.caption("Les 12 localités les plus équipées, mois par mois — pour repérer d'un coup d'œil où et quand "
                   "l'effort d'installation s'est concentré.")
        localites_crois = toutes_localites_crois[:12]
    else:
        st.caption(f"Les {len(toutes_localites_crois)} localités, mois par mois — tableau et graphe complets, "
                   "sans limite de nombre de localités.")
        localites_crois = toutes_localites_crois

    df_crois = df[df["localite"].isin(localites_crois)]
    if df_crois.empty:
        st.info("Pas assez de données pour un croisement.")
    else:
        pivot = (df_crois.groupby(["localite", "periode"]).size().reset_index(name="Compteurs")
                 .pivot(index="localite", columns="periode", values="Compteurs").fillna(0))
        pivot = pivot.reindex(localites_crois)
        pivot.columns = [c.strftime("%m/%Y") for c in pivot.columns]
        fig = go.Figure(data=go.Heatmap(
            z=pivot.values, x=pivot.columns, y=pivot.index,
            colorscale=[[0, "#F2F2F2"], [1, NAVY]], hoverongaps=False,
            colorbar=dict(title="Compteurs"),
        ))
        fig = plotly_base_layout(fig, height=max(360, 28 * len(pivot)), legend=False)
        st.plotly_chart(fig, width="stretch")
        with st.expander("📋 Voir le tableau croisé", expanded=(len(localites_crois) > 12)):
            st.dataframe(pivot.astype(int), width="stretch", height=min(600, 38 * (len(pivot) + 1)))
            suffixe_fichier = "toutes_localites" if len(localites_crois) > 12 else "top12"
            st.download_button("⬇️ Télécharger ce tableau croisé (CSV)", pivot.astype(int).to_csv().encode("utf-8"),
                                f"compteurs_localite_x_periode_{suffixe_fichier}.csv", "text/csv",
                                key="cpt_dl_croisement")

# -----------------------------------------------------------------------
# Par phase du projet
# -----------------------------------------------------------------------
with tab_phase:
    section_title("STATISTIQUES PAR PHASE DU PROJET")
    noms_phases = [str(p).strip() for p in phases_editees["Phase"].tolist() if pd.notna(p) and str(p).strip()]
    if not noms_phases:
        st.info(
            "Définis au moins une phase (nom + dates de début/fin) dans l'encadré « 🏗️ Phases du projet » "
            "de la barre latérale pour voir les statistiques par phase."
        )
    else:
        n_hors_phase = int((df["phase"] == "(hors phase)").sum())
        if n_hors_phase:
            st.warning(
                f"{n_hors_phase} compteur(s) ont une période d'installation en dehors de toutes les phases "
                "définies — ajuste les dates de début/fin dans la barre latérale si besoin."
            )
        st.caption(
            "Les plages de dates de chaque phase sont définies et modifiables dans la barre latérale "
            "(« 🏗️ Phases du projet ») — aucune colonne « phase » n'existe dans les exports Holley, ce "
            "classement est donc entièrement basé sur la période d'installation de chaque compteur."
        )

        ordre_phases = noms_phases + (["(hors phase)"] if n_hors_phase else [])
        par_phase = df["phase"].value_counts().reindex(ordre_phases).fillna(0).astype(int)
        classees = par_phase.drop("(hors phase)", errors="ignore")
        phase_top = classees.idxmax() if not classees.empty and classees.max() > 0 else "—"

        kpi_row([
            ("🏗️ Phases définies", str(len(noms_phases)), None),
            ("🥇 Phase la plus équipée", phase_top, None),
            ("🔌 Compteurs classés", f"{int(classees.sum()):,}".replace(",", " "), None),
            ("❓ Compteurs hors phase", str(n_hors_phase), None),
        ])

        st.write("")
        section_title("COMPTEURS INSTALLÉS PAR PHASE")
        df_par_phase = par_phase.reset_index()
        df_par_phase.columns = ["Phase", "Compteurs installés"]
        couleurs_phase = [GREY if p == "(hors phase)" else NAVY for p in df_par_phase["Phase"]]
        fig = px.bar(df_par_phase, x="Phase", y="Compteurs installés", text="Compteurs installés",
                     category_orders={"Phase": ordre_phases})
        fig.update_traces(marker_color=couleurs_phase, textposition="outside")
        fig = plotly_base_layout(fig, height=340, legend=False)
        st.plotly_chart(fig, width="stretch")

        st.write("")
        section_title("ÉVOLUTION DES INSTALLATIONS PAR PHASE, DANS LE TEMPS")
        granularite_phase = st.radio(
            "Granularité", ["Mois", "Trimestre", "Année"], horizontal=True, index=0, key="cpt_gran_phase",
        )
        code_periode_phase = {"Mois": "M", "Trimestre": "Q", "Année": "Y"}[granularite_phase]
        df_phase_temps = df.copy()
        df_phase_temps["bucket"] = df_phase_temps["periode"].dt.to_period(code_periode_phase).dt.to_timestamp()
        par_bucket_phase = df_phase_temps.groupby(["bucket", "phase"]).size().reset_index(name="Compteurs")
        ordre_phases_presentes = [p for p in ordre_phases if p in par_bucket_phase["phase"].unique()]

        fig_evol = px.bar(
            par_bucket_phase, x="bucket", y="Compteurs", color="phase",
            category_orders={"phase": ordre_phases_presentes}, color_discrete_sequence=CATEGORICAL,
        )
        fig_evol.update_layout(barmode="stack")
        fig_evol = plotly_base_layout(fig_evol, height=380, legend=True)
        fig_evol.update_xaxes(title=None)
        st.plotly_chart(fig_evol, width="stretch")

        section_title("CUMUL DES INSTALLATIONS PAR PHASE, DANS LE TEMPS")
        par_bucket_phase_cumul = par_bucket_phase.sort_values("bucket").copy()
        par_bucket_phase_cumul["Cumul"] = par_bucket_phase_cumul.groupby("phase")["Compteurs"].cumsum()
        fig_cumul = px.line(
            par_bucket_phase_cumul, x="bucket", y="Cumul", color="phase",
            category_orders={"phase": ordre_phases_presentes}, color_discrete_sequence=CATEGORICAL, markers=True,
        )
        fig_cumul = plotly_base_layout(fig_cumul, height=340, legend=True)
        fig_cumul.update_xaxes(title=None)
        fig_cumul.update_traces(line=dict(width=2.5))
        st.plotly_chart(fig_cumul, width="stretch")

        st.write("")
        section_title("TABLEAU CROISÉ PHASE × PÉRIODE")
        pivot_phase = (df_phase_temps.groupby(["phase", "bucket"]).size().reset_index(name="Compteurs")
                       .pivot(index="phase", columns="bucket", values="Compteurs").fillna(0))
        pivot_phase = pivot_phase.reindex(ordre_phases_presentes)
        format_colonne = "%Y" if granularite_phase == "Année" else "%m/%Y"
        pivot_phase.columns = [c.strftime(format_colonne) for c in pivot_phase.columns]
        with st.expander("📋 Voir le tableau croisé phase × période", expanded=True):
            st.dataframe(pivot_phase.astype(int), width="stretch",
                         height=min(400, 38 * (len(pivot_phase) + 1)))
            st.download_button(
                "⬇️ Télécharger ce tableau croisé (CSV)", pivot_phase.astype(int).to_csv().encode("utf-8"),
                "compteurs_phase_x_periode.csv", "text/csv", key="cpt_dl_phase_periode",
            )

st.write("")
with st.expander("📄 Export complet des compteurs (toutes colonnes nettoyées)"):
    colonnes_export = [c for c in ["numero_compteur", "localite", "poste", "phase", "categorie", "type_compteur",
                                    "solaire", "periode", "nom_fichier"] if c in df.columns]
    st.dataframe(df[colonnes_export], width="stretch", hide_index=True, height=400)
    st.download_button("⬇️ Télécharger toutes les lignes (CSV)", df[colonnes_export].to_csv(index=False).encode("utf-8"),
                        f"compteurs_export_{date.today().isoformat()}.csv", "text/csv", key="cpt_dl_export")

render_sidebar_footer(data.generated_on if data else "")
