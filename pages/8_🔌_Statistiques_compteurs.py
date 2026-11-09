from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from utils.ui import inject_base_style, BarreChargement  # thème de l'application + contrôle d'accès
from utils.theme_compteurs import (
    PAGE_ICON, APP_TITLE, NAVY, BLUE, GOLD, GREY, CATEGORICAL, BG_SURFACE,
    inject_component_style, section_title, kpi_row, mini_metric, status_badge,
    animated_counter, flow_diagram, saturation_bar, plotly_base_layout, render_sidebar_footer,
    kpi_card_row, gauge_chart,
)
from utils.compteurs import (
    read_excel_sheet_names, load_excel,
    est_format_holley, parse_date_from_filename, build_from_holley_files,
    apply_column_mapping, locality_cleanup_ui, lot_summary, load_official_sites,
    default_phases, assign_phases, assign_phases_combined, default_targets, target_status,
    coverage_stats, regional_breakdown, detect_duplicates, detect_dormant_postes,
    data_quality_summary, build_pdf_report,
    load_puissances_sites, saturation_par_site, WATTS_PAR_COMPTEUR,
    SEUIL_SATURATION_AVERTISSEMENT, cache_dataframe, lire_fichier_compteurs,
)

st.set_page_config(page_title=APP_TITLE, page_icon=PAGE_ICON, layout="wide")
inject_base_style()
inject_component_style()

st.title("🔌 Statistiques des compteurs")
st.caption("Compteurs (abonnés) installés — répartition par localité et par période d'installation, à partir "
           "des exports du système de gestion des compteurs prépayés « Holley ».")

with st.expander("ℹ️ Ce que cette page représente exactement — à lire avant de l'utiliser", expanded=False):
    st.markdown(
        """
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

**Persistance :** Streamlit ne conserve rien entre deux sessions — les fichiers déposés ici sont à
re-déposer à chaque ouverture. Tous les tableaux de cette application s'exportent en CSV.

**Identité visuelle :** cette application reprend la palette du tableau de bord AER (parc solaire /
ressources humaines) pour une cohérence visuelle entre les outils AER, mais lit ses propres fichiers de
façon totalement indépendante de ce tableau de bord.
        """
    )

# =============================================================================
# Barre latérale — navigation
# =============================================================================
NAV_SECTIONS = [
    ("vue", "📊", "Vue d'ensemble"),
    ("localite", "📍", "Par localité"),
    ("periode", "📅", "Par période"),
    ("croisement", "🧭", "Localité × période"),
    ("phase", "🏗️", "Par phase"),
    ("region", "🌍", "Par région"),
    ("saturation", "⚡", "Saturation des sites"),
    ("qualite", "🔍", "Qualité des données"),
]
LIBELLES_NAV = [f"{icone}  {libelle}" for _, icone, libelle in NAV_SECTIONS]
CLE_PAR_LIBELLE = {f"{icone}  {libelle}": cle for cle, icone, libelle in NAV_SECTIONS}

st.sidebar.markdown('<div class="aer-nav-brand">🔌 Statistiques compteurs</div>', unsafe_allow_html=True)
libelle_choisi = st.sidebar.radio(
    "Navigation", LIBELLES_NAV, label_visibility="collapsed", key="cpt_nav_radio",
)
nav_actif = CLE_PAR_LIBELLE[libelle_choisi]
st.sidebar.markdown("---")

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
barre = None
if uploaded_files:
    # Barre affichée seulement quand le jeu de fichiers change (les relectures sont en cache).
    signature = tuple(sorted((uf.name, uf.size) for uf in uploaded_files))
    if st.session_state.get("_cpt_signature") != signature:
        barre = BarreChargement("Chargement des fichiers de compteurs…", total=len(uploaded_files) + 2)
    lus, erreurs = [], []
    for i, uf in enumerate(uploaded_files, start=1):
        try:
            raw = lire_fichier_compteurs(uf.name, uf.getvalue())
        except Exception as e:  # noqa: BLE001
            erreurs.append(f"{uf.name} : {e}")
            continue
        finally:
            if barre:
                barre.etape(f"Lecture du fichier {i}/{len(uploaded_files)} : {uf.name}")
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

    if barre:
        barre.etape("Assemblage des lots et rapprochement des localités")
    if df_brut is not None and not df_brut.empty:
        df = locality_cleanup_ui(df_brut)
    if barre:
        barre.etape("Données prêtes")
        barre.fin()
        st.session_state["_cpt_signature"] = signature

if df is None:
    st.sidebar.info(
        "Aucun fichier chargé — l'application démarre **vide, sans aucune donnée fictive**. Dépose tes "
        "fichiers Excel ci-dessus pour voir tes vraies statistiques de compteurs."
    )
    st.info(
        "Aucune donnée de compteurs pour l'instant. En attendant, voici les **localités officielles du "
        "parc solaire AER** que l'application reconnaît et vers lesquelles elle corrige automatiquement "
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
    st.caption(
        "Convention communiquée par l'utilisateur, prioritaire sur les dates ci-dessus : un numéro de "
        "série (SN) commençant par **251** → Phase 1, **241** → Phase 2, **5** → Phase 3 (ordre des lignes "
        "ci-dessus, pas leur nom). Les plages de dates ne servent plus que pour les numéros ne correspondant "
        "à aucun de ces préfixes — à ajuster dans `utils/compteurs.py` (`PREFIXES_COMPTEUR_PHASE`) si une "
        "autre convention s'applique."
    )
df["phase"], phase_desaccord = assign_phases_combined(df, phases_editees)
cache_dataframe(df)  # résumé repris dans l'onglet « Statistiques compteurs » de l'accueil

# =============================================================================
# Barre latérale — objectifs par phase (aucune cible chiffrée n'existe dans
# les exports Holley : purement déclaratif, comme les phases elles-mêmes)
# =============================================================================
noms_phases_actuelles = [str(p).strip() for p in phases_editees["Phase"].tolist() if pd.notna(p) and str(p).strip()]
st.sidebar.markdown("### 🎯 Objectifs du projet")
if "cpt_targets_df" not in st.session_state:
    st.session_state["cpt_targets_df"] = default_targets(noms_phases_actuelles)
else:
    existant = st.session_state["cpt_targets_df"]
    deja_connus = existant["Phase"].tolist()
    nouveaux_noms = [n for n in noms_phases_actuelles if n not in deja_connus]
    if nouveaux_noms:
        existant = pd.concat(
            [existant, default_targets(nouveaux_noms)], ignore_index=True,
        )
    st.session_state["cpt_targets_df"] = existant[existant["Phase"].isin(noms_phases_actuelles)].reset_index(drop=True)
with st.sidebar.expander("Définir les objectifs (cibles éditables)", expanded=False):
    st.caption(
        "Aucun objectif chiffré n'existe dans les exports Holley ni ailleurs dans cette application — "
        "saisis la cible de compteurs pour chaque phase (0 = pas de suivi d'objectif pour cette phase)."
    )
    targets_editees = st.data_editor(
        st.session_state["cpt_targets_df"], hide_index=True, width="stretch",
        column_config={
            "Phase": st.column_config.TextColumn("Phase", disabled=True),
            "Objectif (compteurs)": st.column_config.NumberColumn("Objectif (compteurs)", min_value=0, step=10),
        },
        key="cpt_targets_editor",
    )
    st.session_state["cpt_targets_df"] = targets_editees

sites_ref = load_official_sites()
puissances_ref = load_puissances_sites()

# =============================================================================
# Filtre global — s'applique à TOUTE l'application (bandeau central,
# graphiques, tableaux, export, rapport PDF), pas seulement à la section
# affichée dans la barre latérale. Remplace les filtres qui n'existaient
# jusqu'ici que dans certaines sections (ex. l'ancien filtre par poste de
# « Par localité », l'ancienne plage de dates de « Par période ») pour
# n'avoir qu'un seul endroit où filtrer les données.
# =============================================================================
df_avant_filtre = df
df_region_avant_filtre = regional_breakdown(df_avant_filtre, sites_ref) if not sites_ref.empty else pd.DataFrame()

with st.container(border=True):
    section_title("🔎 FILTRES — S'APPLIQUENT À TOUTE L'APPLICATION")
    fc1, fc2, fc3, fc4 = st.columns(4)
    with fc1:
        filtre_localites = st.multiselect(
            "Localité", sorted(df_avant_filtre["localite"].dropna().unique().tolist()),
            default=[], key="flt_localite",
        )
    with fc2:
        options_postes = sorted(df_avant_filtre["poste"].dropna().unique().tolist()) if "poste" in df_avant_filtre else []
        filtre_postes = st.multiselect("Poste", options_postes, default=[], key="flt_poste", disabled=not options_postes)
    with fc3:
        options_regions = (sorted(df_region_avant_filtre["region"].dropna().unique().tolist())
                            if not df_region_avant_filtre.empty else [])
        filtre_regions = st.multiselect("Région", options_regions, default=[], key="flt_region",
                                         disabled=not options_regions)
    with fc4:
        options_phases = sorted(df_avant_filtre["phase"].dropna().unique().tolist())
        filtre_phases = st.multiselect("Phase", options_phases, default=[], key="flt_phase")

    fc5, fc6, fc7 = st.columns([1, 1, 1])
    with fc5:
        options_types = (sorted(df_avant_filtre["type_compteur"].dropna().unique().tolist())
                          if "type_compteur" in df_avant_filtre else [])
        filtre_types = st.multiselect("Type de compteur", options_types, default=[], key="flt_type",
                                       disabled=not options_types)
    with fc6:
        date_min_f, date_max_f = df_avant_filtre["periode"].min().date(), df_avant_filtre["periode"].max().date()
        if date_min_f == date_max_f:
            st.caption(f"Période disponible : {date_min_f.strftime('%m/%Y')} (un seul lot chargé)")
            plage_dates_filtre = (date_min_f, date_max_f)
        else:
            plage_dates_filtre = st.date_input(
                "Période d'installation", value=(date_min_f, date_max_f),
                min_value=date_min_f, max_value=date_max_f, key="flt_dates",
            )
    with fc7:
        st.write("")
        if st.button("↺ Réinitialiser les filtres", key="flt_reset", width="stretch"):
            for cle in ["flt_localite", "flt_poste", "flt_region", "flt_phase", "flt_type", "flt_dates"]:
                st.session_state.pop(cle, None)
            st.rerun()

    masque_filtre = pd.Series(True, index=df_avant_filtre.index)
    if filtre_localites:
        masque_filtre &= df_avant_filtre["localite"].isin(filtre_localites)
    if filtre_postes and "poste" in df_avant_filtre:
        masque_filtre &= df_avant_filtre["poste"].isin(filtre_postes)
    if filtre_regions and not df_region_avant_filtre.empty:
        masque_filtre &= df_region_avant_filtre["region"].isin(filtre_regions)
    if filtre_phases:
        masque_filtre &= df_avant_filtre["phase"].isin(filtre_phases)
    if filtre_types and "type_compteur" in df_avant_filtre:
        masque_filtre &= df_avant_filtre["type_compteur"].isin(filtre_types)
    if isinstance(plage_dates_filtre, tuple) and len(plage_dates_filtre) == 2:
        debut_f, fin_f = plage_dates_filtre
        masque_filtre &= ((df_avant_filtre["periode"].dt.date >= debut_f) &
                           (df_avant_filtre["periode"].dt.date <= fin_f))

    df = df_avant_filtre[masque_filtre].copy()
    phase_desaccord = phase_desaccord[masque_filtre]
    if len(df) < len(df_avant_filtre):
        st.caption(
            f"Filtres actifs : {len(df):,} / {len(df_avant_filtre):,} compteurs affichés dans toute "
            "l'application.".replace(",", " ")
        )
    if df.empty:
        st.warning("Aucun compteur ne correspond à ces filtres — élargis-les ou réinitialise-les ci-dessus.")
        st.stop()

df_saturation = saturation_par_site(df, sites_ref, puissances_ref)

# =============================================================================
# KPI globaux
# =============================================================================
total = len(df)
nb_localites = df["localite"].nunique()
nb_postes = df["poste"].nunique() if "poste" in df else None
derniere_periode = df["periode"].max()
nb_solaire = int(df["solaire"].sum()) if "solaire" in df else 0
taux_solaire = f"{nb_solaire / total * 100:.0f} %" if total else "—"

# =============================================================================
# Bandeau central — panneau de supervision (compromis "néon réservé aux
# états" validé avec l'utilisateur : le Total occupe le centre de gravité
# visuel, le statut actif/inactif est le SEUL élément qui respire).
# =============================================================================
recence_jours = (pd.Timestamp.now() - derniere_periode).days if pd.notna(derniere_periode) else None
# Heuristique assumée (à défaut d'une date de "dernière synchronisation" dans
# les fichiers Holley) : installations jugées "actives" si le dernier lot
# déposé est daté de moins de 90 jours par rapport à aujourd'hui — un fichier
# déposé longtemps après sa période réelle fera apparaître "Aucune
# installation récente" même si le projet est toujours en cours.
actif = recence_jours is not None and recence_jours <= 90
statut_label = "Installations actives" if actif else "Aucune installation récente"
statut_code = "ok" if actif else "neutral"

with st.container():
    st.markdown('<div class="aer-glass">', unsafe_allow_html=True)
    hero_g, hero_c, hero_d = st.columns([1, 1.5, 1])
    with hero_g:
        status_badge(statut_label, statut_code, pulse=actif)
        st.write("")
        mini_metric("📍 Localités couvertes", nb_localites)
        mini_metric("🗺️ Postes couverts", nb_postes if nb_postes else "—")
    with hero_c:
        animated_counter("🔌 Compteurs installés — total", total, status="info", key="hero_total")
    with hero_d:
        mini_metric("📅 Dernière période", derniere_periode.strftime("%m/%Y") if pd.notna(derniere_periode) else "—")
        mini_metric("☀️ Compteurs solaires", taux_solaire)
    st.markdown('</div>', unsafe_allow_html=True)

if nb_postes:
    par_poste_flux = df["poste"].value_counts()
    SEUIL_FLUX = 6
    tete_flux = par_poste_flux.head(SEUIL_FLUX)
    reste_flux = int(par_poste_flux.iloc[SEUIL_FLUX:].sum())
    flux_postes = list(tete_flux.items())
    if reste_flux:
        flux_postes.append(("Autres postes", reste_flux))

    st.write("")
    section_title("FLUX D'INSTALLATION — DES POSTES HOLLEY VERS LE TOTAL")
    st.caption(
        "Chaque poste Holley alimente ses localités, qui remontent vers le total général — les "
        f"{min(SEUIL_FLUX, len(par_poste_flux))} postes les plus actifs sont détaillés, le reste est agrégé "
        "sous « Autres postes »."
    )
    flow_diagram(flux_postes, nb_localites, total, key="hero_flow")

# =============================================================================
# Bandeau de contrôle — couverture du référentiel officiel + qualité des
# données, toujours visible (pas besoin d'ouvrir un onglet pour les voir)
# =============================================================================
couverture = coverage_stats(df, sites_ref)
doublons_apercu = detect_duplicates(df)
dormants_apercu = detect_dormant_postes(df)
qualite = data_quality_summary(df)

nb_phase_desaccord = int(phase_desaccord.sum())
colonnes_desaccord = [c for c in ["sn", "numero_compteur", "localite", "poste", "periode"] if c in df.columns]
desaccord_apercu = df.loc[phase_desaccord, colonnes_desaccord + ["phase"]].copy()
if not desaccord_apercu.empty:
    desaccord_apercu["phase (date)"] = assign_phases(df.loc[phase_desaccord], phases_editees)
    desaccord_apercu = desaccord_apercu.rename(columns={"phase": "phase (préfixe)"})

nb_sites_satures = int((df_saturation["statut"] == "critical").sum()) if not df_saturation.empty else 0

st.write("")
ctrl1, ctrl2, ctrl3, ctrl4 = st.columns(4)
with ctrl1:
    if couverture["taux"] is not None:
        mini_metric(
            "📊 Couverture localités officielles",
            f"{couverture['couvertes']} / {couverture['total']} ({couverture['taux'] * 100:.0f} %)",
        )
    else:
        mini_metric("📊 Couverture localités officielles", "—")
with ctrl2:
    statut_doublons = "critical" if len(doublons_apercu) else "ok"
    status_badge(
        f"{len(doublons_apercu)} compteur(s) en doublon" if len(doublons_apercu) else "Aucun doublon détecté",
        statut_doublons,
    )
with ctrl3:
    statut_dormants = "warning" if len(dormants_apercu) else "ok"
    status_badge(
        f"{len(dormants_apercu)} poste(s) inactif(s) (> 90 j)" if len(dormants_apercu) else "Tous les postes actifs",
        statut_dormants,
    )
with ctrl4:
    if df_saturation.empty:
        status_badge("Saturation non calculable", "neutral")
    else:
        statut_saturation_apercu = "critical" if nb_sites_satures else "ok"
        status_badge(
            f"{nb_sites_satures} site(s) en sursaturation" if nb_sites_satures else "Aucun site en sursaturation",
            statut_saturation_apercu, pulse=bool(nb_sites_satures),
        )
st.caption("Détail et méthode dans les onglets « ⚡ Saturation des sites » et « 🔍 Qualité des données ».")

st.write("")

# La navigation se fait désormais par la barre latérale (nav_actif, ci-dessus) plutôt que
# par des onglets en haut de page — chaque section ci-dessous ne s'affiche que si elle est active.

# Données communes à plusieurs sections ET au rapport PDF plus bas — toujours
# calculées ici, indépendamment de la section actuellement affichée dans la
# barre latérale, pour que le PDF reflète toujours les vraies données plutôt
# qu'une valeur par défaut parce qu'une autre section était ouverte au moment
# de la génération (avec la navigation par onglets d'avant, tout s'exécutait
# à chaque rafraîchissement ; avec la barre latérale, seule la section active
# s'exécute, donc ce qui est partagé doit être calculé ici, une fois pour toutes).
noms_phases = [str(p).strip() for p in phases_editees["Phase"].tolist() if pd.notna(p) and str(p).strip()]
n_hors_phase = int((df["phase"] == "(hors phase)").sum())
ordre_phases = noms_phases + (["(hors phase)"] if n_hors_phase else [])
if noms_phases:
    par_phase = df["phase"].value_counts().reindex(ordre_phases).fillna(0).astype(int)
    df_par_phase = par_phase.reset_index()
    df_par_phase.columns = ["Phase", "Compteurs installés"]
else:
    df_par_phase = pd.DataFrame(columns=["Phase", "Compteurs installés"])

objectifs_definis = targets_editees[targets_editees["Objectif (compteurs)"] > 0]
if not objectifs_definis.empty:
    fusion_obj = targets_editees.merge(df_par_phase, on="Phase", how="left")
    fusion_obj["Compteurs installés"] = fusion_obj["Compteurs installés"].fillna(0).astype(int)
else:
    fusion_obj = pd.DataFrame()

if not sites_ref.empty:
    df_region = regional_breakdown(df, sites_ref)
    par_region = df_region["region"].value_counts().reset_index()
    par_region.columns = ["Région", "Compteurs installés"]
else:
    df_region = pd.DataFrame()
    par_region = pd.DataFrame(columns=["Région", "Compteurs installés"])

# -----------------------------------------------------------------------
# Vue d'ensemble
# -----------------------------------------------------------------------
if nav_actif == "vue":
    with st.container(border=True):
        section_title("TOP 10 DES LOCALITÉS")
        top10 = df["localite"].value_counts().head(10).reset_index()
        top10.columns = ["Localité", "Compteurs installés"]
        fig = px.bar(top10.sort_values("Compteurs installés"), x="Compteurs installés", y="Localité",
                     orientation="h", color_discrete_sequence=[NAVY])
        fig = plotly_base_layout(fig, height=360, legend=False)
        st.plotly_chart(fig, width="stretch")

    st.write("")

    if couverture["taux"] is not None:
        col_jauge, col_rythme = st.columns([1, 2])
        with col_jauge:
            with st.container(border=True):
                section_title("COUVERTURE DU RÉFÉRENTIEL OFFICIEL")
                st.plotly_chart(
                    gauge_chart(couverture["taux"] * 100, "% des 499 sites officiels couverts", key="gauge_couverture"),
                    width="stretch",
                )
                st.caption(f"{couverture['couvertes']} / {couverture['total']} sites ont au moins un compteur installé.")
        with col_rythme:
            with st.container(border=True):
                section_title("RYTHME D'INSTALLATION — PÉRIODES LES PLUS RÉCENTES")
                par_periode_apercu = df.groupby("periode").size().reset_index(name="Installations")
                par_periode_apercu = par_periode_apercu.sort_values("periode").tail(12)
                fig2 = px.bar(par_periode_apercu, x="periode", y="Installations", color_discrete_sequence=[BLUE])
                fig2 = plotly_base_layout(fig2, height=300, legend=False)
                fig2.update_xaxes(title=None)
                st.plotly_chart(fig2, width="stretch")
        st.write("")
    else:
        with st.container(border=True):
            section_title("RYTHME D'INSTALLATION — PÉRIODES LES PLUS RÉCENTES")
            par_periode_apercu = df.groupby("periode").size().reset_index(name="Installations")
            par_periode_apercu = par_periode_apercu.sort_values("periode").tail(12)
            fig2 = px.bar(par_periode_apercu, x="periode", y="Installations", color_discrete_sequence=[BLUE])
            fig2 = plotly_base_layout(fig2, height=300, legend=False)
            fig2.update_xaxes(title=None)
            st.plotly_chart(fig2, width="stretch")
        st.write("")

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
if nav_actif == "localite":
    df_loc = df  # déjà filtré par le panneau de filtres global, en haut de page
    if df_loc.empty:
        st.warning("Aucune localité ne correspond au filtre choisi.")
    else:
        par_loc = df_loc["localite"].value_counts().reset_index()
        par_loc.columns = ["Localité", "Compteurs installés"]
        localite_top = par_loc.iloc[0]

        kpi_card_row([
            ("📍", "Localités couvertes", str(df_loc["localite"].nunique())),
            ("🥇", "Localité la plus équipée", localite_top["Localité"]),
            ("🔌", f"Compteurs à {localite_top['Localité']}", str(int(localite_top["Compteurs installés"]))),
            ("📊", "Compteurs / localité (moy.)", f"{len(df_loc) / df_loc['localite'].nunique():.0f}"),
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
            # Trier AVANT de calculer les couleurs : px.bar reçoit les lignes triées,
            # donc le tableau de couleurs doit suivre le même ordre (sinon la couleur
            # d'une barre ne correspond plus à son type — bug repéré en vérifiant le
            # rendu de cette refonte, corrigé au passage).
            par_type = par_type.sort_values("Compteurs installés")
            couleurs_type = [GOLD if ("SOLAR" in t or "SOLAIRE" in t) else BLUE for t in par_type["Type de compteur"]]
            fig_t = px.bar(par_type, x="Compteurs installés", y="Type de compteur",
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
if nav_actif == "periode":
    date_min, date_max = df["periode"].min().date(), df["periode"].max().date()
    if date_min == date_max:
        st.caption(f"Période disponible : {date_min.strftime('%m/%Y')} (un seul lot chargé)")
    else:
        st.caption(
            f"Période couverte par les filtres actifs : {date_min.strftime('%m/%Y')} → {date_max.strftime('%m/%Y')} "
            "— ajuste la plage de dates dans le panneau de filtres en haut de page si besoin."
        )
    granularite = st.radio("Granularité", ["Mois", "Trimestre", "Année"], horizontal=True, index=0, key="cpt_gran")

    periode_df = df  # déjà filtré par le panneau de filtres global, en haut de page

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

        # Variation vs la période précédente (le dernier "bucket" affiché contre
        # celui juste avant — nécessite au moins 2 buckets dans la plage choisie ;
        # delta natif Streamlit, pas de composant personnalisé nécessaire).
        delta_texte = None
        if len(par_bucket) >= 2:
            dernier = int(par_bucket["Nouvelles installations"].iloc[-1])
            precedent = int(par_bucket["Nouvelles installations"].iloc[-2])
            if precedent:
                variation = (dernier - precedent) / precedent * 100
                delta_texte = f"{variation:+.0f} % vs {granularite.lower()} précédent(e)"
            else:
                delta_texte = f"+{dernier} vs {granularite.lower()} précédent(e) (nul)"

        kpi_row([
            ("🔌 Installations sur la période", f"{len(periode_df):,}".replace(",", " "), None),
            (f"📈 Moyenne par {granularite.lower()}", f"{moyenne:.0f}", None),
            (f"🏆 Meilleur(e) {granularite.lower()}",
             meilleure["bucket"].strftime("%m/%Y") if granularite != "Année" else meilleure["bucket"].strftime("%Y"),
             f"{int(meilleure['Nouvelles installations'])} installations"),
            (f"↕️ Dernier {granularite.lower()} vs précédent", f"{int(par_bucket['Nouvelles installations'].iloc[-1]):,}".replace(",", " "), delta_texte),
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
if nav_actif == "croisement":
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
            colorscale=[[0, BG_SURFACE], [1, NAVY]], hoverongaps=False,
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
if nav_actif == "phase":
    section_title("STATISTIQUES PAR PHASE DU PROJET")
    if not noms_phases:
        st.info(
            "Définis au moins une phase (nom + dates de début/fin) dans l'encadré « 🏗️ Phases du projet » "
            "de la barre latérale pour voir les statistiques par phase."
        )
    else:
        if n_hors_phase:
            st.warning(
                f"{n_hors_phase} compteur(s) ont une période d'installation en dehors de toutes les phases "
                "définies — ajuste les dates de début/fin dans la barre latérale si besoin."
            )
        st.caption(
            "Classement prioritaire : numéro de série (colonne SN) commençant par **251** → 1re phase ci-dessus, "
            "**241** → 2e phase, **5** → 3e phase (convention communiquée par l'utilisateur). Les plages de "
            "dates, définies et modifiables dans la barre latérale (« 🏗️ Phases du projet »), ne servent plus "
            "que pour les numéros ne correspondant à aucun de ces préfixes."
        )
        if nb_phase_desaccord:
            st.warning(
                f"{nb_phase_desaccord} compteur(s) ont un préfixe et une plage de dates qui se contredisent — "
                "détail dans l'onglet « 🔍 Qualité des données »."
            )

        par_phase = df["phase"].value_counts().reindex(ordre_phases).fillna(0).astype(int)
        classees = par_phase.drop("(hors phase)", errors="ignore")
        phase_top = classees.idxmax() if not classees.empty and classees.max() > 0 else "—"

        kpi_card_row([
            ("🏗️", "Phases définies", str(len(noms_phases))),
            ("🥇", "Phase la plus équipée", phase_top),
            ("🔌", "Compteurs classés", f"{int(classees.sum()):,}".replace(",", " ")),
            ("❓", "Compteurs hors phase", str(n_hors_phase)),
        ])

        st.write("")
        with st.container(border=True):
            section_title("COMPTEURS INSTALLÉS PAR PHASE")
            couleurs_phase = [GREY if p == "(hors phase)" else NAVY for p in df_par_phase["Phase"]]
            fig = px.bar(df_par_phase, x="Phase", y="Compteurs installés", text="Compteurs installés",
                         category_orders={"Phase": ordre_phases})
            fig.update_traces(marker_color=couleurs_phase, textposition="outside")
            fig = plotly_base_layout(fig, height=340, legend=False)
            st.plotly_chart(fig, width="stretch")

        st.write("")
        section_title("OBJECTIFS VS RÉALISÉ")
        if objectifs_definis.empty:
            st.caption(
                "Aucun objectif chiffré saisi — définis une cible par phase dans la barre latérale "
                "(« 🎯 Objectifs du projet ») pour voir l'écart réalisé / objectif ici."
            )
        else:
            badges_cols = st.columns(len(fusion_obj)) if len(fusion_obj) else []
            for col, (_, ligne) in zip(badges_cols, fusion_obj.iterrows()):
                with col:
                    statut = target_status(int(ligne["Compteurs installés"]), int(ligne["Objectif (compteurs)"]))
                    libelle = (
                        f"{ligne['Phase']} — pas d'objectif" if statut == "neutral"
                        else f"{ligne['Phase']} — {ligne['Compteurs installés']}/{ligne['Objectif (compteurs)']}"
                    )
                    status_badge(libelle, statut)
            st.write("")
            fig_obj = go.Figure()
            fig_obj.add_bar(x=fusion_obj["Phase"], y=fusion_obj["Objectif (compteurs)"], name="Objectif",
                             marker_color=GREY, marker_opacity=.55)
            fig_obj.add_bar(x=fusion_obj["Phase"], y=fusion_obj["Compteurs installés"], name="Réalisé",
                             marker_color=NAVY)
            fig_obj.update_layout(barmode="group")
            fig_obj = plotly_base_layout(fig_obj, height=340, legend=True)
            st.plotly_chart(fig_obj, width="stretch")
            st.caption(
                "Seuils assumés par défaut (aucune tolérance officielle communiquée) : vert si réalisé ≥ "
                "objectif, ambre si ≥ 80 % de l'objectif, rouge en dessous."
            )

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

# -----------------------------------------------------------------------
# Par région — PAS une carte : sites_officiels_aer.csv ne contient aucune
# coordonnée GPS (contrairement au classeur Excel du tableau de bord
# principal, que cette application ne lit volontairement pas). Regroupement
# par région/antenne à partir du référentiel officiel uniquement.
# -----------------------------------------------------------------------
if nav_actif == "region":
    section_title("RÉPARTITION PAR RÉGION / ANTENNE")
    if sites_ref.empty:
        st.info("Référentiel des sites officiels indisponible — impossible de rattacher les localités à une région.")
    else:
        st.caption(
            "⚠️ Ce n'est **pas une carte géographique** — `data/sites_officiels_aer.csv` ne contient aucune "
            "coordonnée GPS, seulement région / département / antenne. Rattachement par correspondance "
            "**exacte** avec le nom de localité déjà corrigé : une localité qui ne correspond à aucun des "
            "499 sites officiels (sous-localité, quartier) apparaît sous « (hors référentiel) », jamais "
            "rattachée à une région devinée."
        )
        hors_ref = int((df_region["region"] == "(hors référentiel)").sum())
        status_badge(
            f"{hors_ref} compteur(s) hors référentiel (sous-localités)" if hors_ref
            else "Toutes les localités installées correspondent à un site officiel",
            "warning" if hors_ref else "ok",
        )
        st.write("")

        couleurs_region = [GREY if r == "(hors référentiel)" else NAVY for r in par_region["Région"]]
        with st.container(border=True):
            fig_region = px.bar(par_region.sort_values("Compteurs installés"), x="Compteurs installés", y="Région",
                                 orientation="h", text="Compteurs installés")
            fig_region.update_traces(marker_color=couleurs_region, textposition="outside")
            fig_region = plotly_base_layout(fig_region, height=max(300, 34 * len(par_region)), legend=False)
            st.plotly_chart(fig_region, width="stretch")

        if df_region["antenne"].nunique() > 1:
            st.write("")
            with st.container(border=True):
                section_title("RÉPARTITION PAR ANTENNE")
                par_antenne = df_region["antenne"].value_counts().reset_index()
                par_antenne.columns = ["Antenne", "Compteurs installés"]
                couleurs_antenne = [GREY if a == "(hors référentiel)" else BLUE for a in par_antenne["Antenne"]]
                fig_antenne = px.bar(par_antenne.sort_values("Compteurs installés"), x="Compteurs installés", y="Antenne",
                                      orientation="h", text="Compteurs installés")
                fig_antenne.update_traces(marker_color=couleurs_antenne, textposition="outside")
                fig_antenne = plotly_base_layout(fig_antenne, height=max(280, 34 * len(par_antenne)), legend=False)
                st.plotly_chart(fig_antenne, width="stretch")

        st.write("")
        section_title("TABLEAU DÉTAILLÉ")
        tableau_region = par_region.copy()
        st.dataframe(tableau_region, width="stretch", hide_index=True)
        st.download_button("⬇️ Télécharger ce tableau (CSV)", tableau_region.to_csv(index=False).encode("utf-8"),
                            "compteurs_par_region.csv", "text/csv", key="cpt_dl_region")

# -----------------------------------------------------------------------
# Saturation des sites — capacité théorique (puissance installée ÷ 400 W
# par compteur, convention communiquée par l'utilisateur) vs compteurs
# réellement installés. Ne concerne que les localités qui correspondent à
# un site officiel (seuls sites dont la puissance est connue) ; une
# localité hors référentiel est déjà signalée ailleurs (onglet Par région).
# -----------------------------------------------------------------------
if nav_actif == "saturation":
    section_title("TAUX DE SATURATION DES SITES")
    if puissances_ref.empty:
        st.info("Référentiel des puissances installées indisponible — impossible de calculer la saturation.")
    elif df_saturation.empty:
        st.info("Référentiel des sites officiels indisponible, ou aucune localité installée ne correspond à un "
                "site officiel — impossible de calculer la saturation.")
    else:
        status_badge(
            f"Convention : {WATTS_PAR_COMPTEUR} W admis par compteur — capacité théorique = puissance du site "
            "(kWc) × 1000 ÷ 400, arrondie à l'entier inférieur.",
            "info",
        )
        st.caption(
            "Règle de dimensionnement communiquée par l'utilisateur, pas une valeur officielle retrouvée dans "
            "les fichiers de cette application — à corriger ici si une autre convention s'applique. Seuls les "
            "sites du référentiel officiel apparaissent (puissance connue) ; une localité installée hors "
            "référentiel (sous-localité, quartier) reste signalée dans l'onglet « 🌍 Par région », jamais "
            "ici avec une capacité devinée."
        )

        nb_critiques = int((df_saturation["statut"] == "critical").sum())
        nb_alertes = int((df_saturation["statut"] == "warning").sum())
        # Moyenne calculée UNIQUEMENT sur les sites ayant au moins un compteur
        # installé — sur les 498 sites référencés, l'incluaient aurait noyé la
        # moyenne sous les ~490 sites jamais encore équipés (0 %), rendant le
        # chiffre incohérent avec son propre libellé.
        saturation_connue = df_saturation.loc[df_saturation["compteurs_installes"] > 0, "taux_saturation"].dropna()
        saturation_moyenne = f"{saturation_connue.mean() * 100:.0f} %" if not saturation_connue.empty else "—"

        kpi_card_row([
            ("⚡", "Sites en sursaturation (≥ 100 %)", str(nb_critiques)),
            ("🟠", f"Sites proches de la capacité (≥ {SEUIL_SATURATION_AVERTISSEMENT * 100:.0f} %)", str(nb_alertes)),
            ("📈", "Saturation moyenne (sites installés)", saturation_moyenne),
            ("🏗️", "Sites référencés (puissance connue)", str(len(df_saturation))),
        ])

        st.write("")
        with st.container(border=True):
            section_title("SITES LES PLUS SATURÉS")
            top_saturation = df_saturation.head(15)
            if top_saturation.empty:
                st.caption("Aucun site installé à afficher.")
            else:
                for _, ligne in top_saturation.iterrows():
                    saturation_bar(
                        ligne["nom"],
                        ligne["taux_saturation"],
                        ligne["statut"],
                        detail=f"{int(ligne['compteurs_installes'])}/{int(ligne['max_compteurs'])} compteurs · "
                                f"{ligne['puissance_kwc']:g} kWc",
                    )

        if nb_critiques:
            st.write("")
            section_title("SITES EN DÉPASSEMENT DE CAPACITÉ THÉORIQUE")
            st.warning(
                f"{nb_critiques} site(s) comptent plus de compteurs installés que leur capacité théorique ne "
                "l'admet — à vérifier : extension de puissance non répercutée ici, compteurs partagés avec un "
                "poste voisin, ou dimensionnement initial sous-estimé."
            )
            colonnes_critiques = ["nom", "region", "antenne", "puissance_kwc", "max_compteurs",
                                   "compteurs_installes", "taux_saturation"]
            tableau_critiques = df_saturation[df_saturation["statut"] == "critical"][colonnes_critiques].copy()
            tableau_critiques["taux_saturation"] = (tableau_critiques["taux_saturation"] * 100).round(0)
            tableau_critiques.columns = ["Site", "Région", "Antenne", "Puissance (kWc)", "Capacité théorique",
                                          "Compteurs installés", "Saturation (%)"]
            st.dataframe(tableau_critiques, width="stretch", hide_index=True)

        st.write("")
        with st.expander("📋 Voir tous les sites référencés (puissance, capacité, saturation)"):
            colonnes_toutes = ["nom", "region", "antenne", "puissance_kwc", "max_compteurs",
                                "compteurs_installes", "taux_saturation", "statut"]
            tableau_complet = df_saturation[colonnes_toutes].copy()
            tableau_complet["taux_saturation"] = (tableau_complet["taux_saturation"] * 100).round(1)
            tableau_complet.columns = ["Site", "Région", "Antenne", "Puissance (kWc)", "Capacité théorique",
                                        "Compteurs installés", "Saturation (%)", "Statut"]
            st.dataframe(tableau_complet, width="stretch", hide_index=True, height=420)
            st.download_button(
                "⬇️ Télécharger ce tableau (CSV)", tableau_complet.to_csv(index=False).encode("utf-8"),
                "compteurs_saturation_sites.csv", "text/csv", key="cpt_dl_saturation",
            )

# -----------------------------------------------------------------------
# Qualité des données — repère les anomalies, ne corrige jamais rien
# automatiquement
# -----------------------------------------------------------------------
if nav_actif == "qualite":
    section_title("QUALITÉ DES DONNÉES CHARGÉES")
    st.caption(
        "Cet onglet signale des anomalies potentielles pour vérification manuelle — rien n'est corrigé ni "
        "retiré automatiquement des statistiques des autres onglets."
    )

    kpi_card_row([
        ("🔁", "Compteurs en doublon", str(len(doublons_apercu))),
        ("💤", "Postes inactifs (> 90 j)", str(len(dormants_apercu))),
        ("⚖️", "Désaccords phase (préfixe vs date)", str(nb_phase_desaccord)),
        ("❓", "Localités non renseignées", f"{qualite.get('taux_localites_non_renseignees', 0) * 100:.1f} %"),
        ("❓", "Postes non renseignés", f"{qualite.get('taux_postes_non_renseignes', 0) * 100:.1f} %"),
    ])

    st.write("")
    section_title("DÉSACCORDS ENTRE LE PRÉFIXE DU COMPTEUR ET LA PLAGE DE DATES DE LA PHASE")
    st.caption(
        "Le préfixe du numéro de compteur (251/241/5) décide la phase affichée partout dans l'application — "
        "ces lignes sont celles où la plage de dates définie dans la barre latérale aurait classé le compteur "
        "dans une AUTRE phase. Peut signaler un compteur posé en stock avant sa phase officielle, une plage de "
        "dates à corriger, ou une erreur de saisie — à vérifier manuellement, jamais résolu automatiquement."
    )
    if desaccord_apercu.empty:
        status_badge("Aucun désaccord entre les deux méthodes de classement par phase", "ok")
    else:
        status_badge(f"{nb_phase_desaccord} compteur(s) classé(s) différemment selon la méthode", "warning")
        st.dataframe(
            desaccord_apercu, width="stretch", hide_index=True,
            height=min(360, 38 * (len(desaccord_apercu) + 1)),
            column_config={"periode": st.column_config.DateColumn("Période", format="MM/YYYY")},
        )
        st.download_button("⬇️ Télécharger ces lignes (CSV)", desaccord_apercu.to_csv(index=False).encode("utf-8"),
                            "compteurs_desaccord_phase.csv", "text/csv", key="cpt_dl_desaccord_phase")

    st.write("")
    section_title("COMPTEURS EN DOUBLON (MÊME NUMÉRO DANS PLUSIEURS LIGNES)")
    if doublons_apercu.empty:
        status_badge("Aucun numéro de compteur en double détecté dans les lots chargés", "ok")
    else:
        status_badge(
            "Vérifie s'il s'agit d'un lot déposé en double ou d'un chevauchement entre deux exports",
            "critical",
        )
        st.dataframe(doublons_apercu, width="stretch", hide_index=True, height=min(360, 38 * (len(doublons_apercu) + 1)))
        st.download_button("⬇️ Télécharger ces lignes (CSV)", doublons_apercu.to_csv(index=False).encode("utf-8"),
                            "compteurs_doublons.csv", "text/csv", key="cpt_dl_doublons")

    st.write("")
    section_title("POSTES SANS NOUVELLE INSTALLATION DEPUIS PLUS DE 90 JOURS")
    if dormants_apercu.empty:
        status_badge("Tous les postes ont une installation récente (moins de 90 jours)", "ok")
    else:
        st.caption("Seuil de 90 jours assumé par défaut (aucune valeur officielle communiquée) — peut indiquer un "
                   "poste à l'arrêt (équipement, connectivité) pendant que d'autres restent actifs.")
        st.dataframe(
            dormants_apercu, width="stretch", hide_index=True,
            column_config={"Dernière_période": st.column_config.DateColumn("Dernière période", format="MM/YYYY")},
        )

    st.write("")
    section_title("VALEURS NON RENSEIGNÉES")
    st.markdown(
        f"- **{qualite.get('localites_non_renseignees', 0)}** ligne(s) sans localité lisible dans le fichier "
        f"source ({qualite.get('taux_localites_non_renseignees', 0) * 100:.1f} % du total).\n"
        f"- **{qualite.get('postes_non_renseignes', 0)}** ligne(s) sans poste lisible "
        f"({qualite.get('taux_postes_non_renseignes', 0) * 100:.1f} % du total)."
    )

st.write("")
with st.expander("📄 Export complet des compteurs (toutes colonnes nettoyées)"):
    colonnes_export = [c for c in ["sn", "numero_compteur", "localite", "poste", "phase", "categorie", "type_compteur",
                                    "solaire", "periode", "nom_fichier"] if c in df.columns]
    st.dataframe(df[colonnes_export], width="stretch", hide_index=True, height=400)
    st.download_button("⬇️ Télécharger toutes les lignes (CSV)", df[colonnes_export].to_csv(index=False).encode("utf-8"),
                        f"compteurs_export_{date.today().isoformat()}.csv", "text/csv", key="cpt_dl_export")

st.write("")
with st.expander("📄 Rapport de synthèse (PDF)"):
    st.caption(
        "Génère un PDF compact (KPI globaux, top localités, objectifs vs réalisé par phase, répartition "
        "régionale, sites en dépassement de capacité, alertes qualité) — pour un reporting institutionnel "
        "sans recomposer ces chiffres à la main. Généré à la demande (pas à chaque interaction) : relance la "
        "génération après un changement de données ou de filtre."
    )
    if st.button("🖨️ Générer le rapport PDF", key="cpt_gen_pdf"):
        with st.spinner("Génération du PDF…"):
            fig_pdf_phase = px.bar(
                df_par_phase, x="Phase", y="Compteurs installés", text="Compteurs installés",
                category_orders={"Phase": ordre_phases} if ordre_phases else None,
            )
            fig_pdf_phase.update_traces(
                marker_color=[GREY if p == "(hors phase)" else NAVY for p in df_par_phase["Phase"]]
            )
            fig_pdf_phase = plotly_base_layout(fig_pdf_phase, height=320, legend=False)

            top10_pdf = df["localite"].value_counts().head(10).reset_index()
            top10_pdf.columns = ["Localité", "Compteurs installés"]
            fig_pdf_top = px.bar(top10_pdf.sort_values("Compteurs installés"), x="Compteurs installés", y="Localité",
                                  orientation="h", color_discrete_sequence=[NAVY])
            fig_pdf_top = plotly_base_layout(fig_pdf_top, height=320, legend=False)

            try:
                img_top = fig_pdf_top.to_image(format="png", width=900, height=420, scale=2)
                img_phase = fig_pdf_phase.to_image(format="png", width=900, height=420, scale=2) if not df_par_phase.empty else None
                erreur_image = None
            except Exception as e:  # noqa: BLE001 — kaleido absent/indisponible sur l'hébergement : PDF sans graphiques plutôt qu'un plantage
                img_top, img_phase, erreur_image = None, None, str(e)

            sections_pdf = []
            if erreur_image:
                sections_pdf.append({
                    "titre": "Graphiques indisponibles",
                    "texte": f"Rendu des graphiques impossible sur cet hebergement (kaleido) : {erreur_image}",
                })
            if img_top:
                sections_pdf.append({"titre": "Top 10 des localites", "image_bytes": img_top})
            if img_phase:
                sections_pdf.append({"titre": "Compteurs installes par phase", "image_bytes": img_phase})
            if not objectifs_definis.empty:
                sections_pdf.append({
                    "titre": "Objectifs vs realise par phase",
                    "tableau": fusion_obj[["Phase", "Objectif (compteurs)", "Compteurs installés"]],
                })
            if not par_region.empty:
                sections_pdf.append({"titre": "Repartition par region", "tableau": par_region})
            if not df_saturation.empty and (df_saturation["statut"] == "critical").any():
                tableau_pdf_saturation = df_saturation[df_saturation["statut"] == "critical"][
                    ["nom", "puissance_kwc", "max_compteurs", "compteurs_installes"]
                ].copy()
                tableau_pdf_saturation.columns = ["Site", "Puissance (kWc)", "Capacite theorique", "Compteurs installes"]
                sections_pdf.append({
                    "titre": "Sites en depassement de capacite theorique (> 400W/compteur)",
                    "tableau": tableau_pdf_saturation,
                })
            sections_pdf.append({
                "titre": "Alertes qualite des donnees",
                "texte": (
                    f"{len(doublons_apercu)} compteur(s) en doublon detecte(s). "
                    f"{len(dormants_apercu)} poste(s) sans nouvelle installation depuis plus de 90 jours. "
                    f"{nb_phase_desaccord} desaccord(s) entre le prefixe du numero de compteur et la plage de "
                    f"dates de la phase. {qualite.get('taux_localites_non_renseignees', 0) * 100:.1f}% des lignes "
                    f"sans localite lisible, {qualite.get('taux_postes_non_renseignes', 0) * 100:.1f}% sans poste "
                    "lisible."
                ),
            })

            pdf_bytes = build_pdf_report(
                "Statistiques des compteurs - AER",
                f"Rapport de synthese genere depuis l'application - {len(uploaded_files)} fichier(s) charge(s)",
                date.today().strftime("%d/%m/%Y"),
                [
                    ("Compteurs installes", f"{total:,}".replace(",", " ")),
                    ("Localites couvertes", str(nb_localites)),
                    ("Couverture referentiel",
                     f"{couverture['taux'] * 100:.0f}%" if couverture["taux"] is not None else "-"),
                    ("Derniere periode", derniere_periode.strftime("%m/%Y") if pd.notna(derniere_periode) else "-"),
                    ("Sites en sursaturation", str(nb_sites_satures)),
                ],
                sections_pdf,
            )
            st.session_state["cpt_pdf_bytes"] = pdf_bytes
        st.success("Rapport généré ci-dessous.")

    if "cpt_pdf_bytes" in st.session_state:
        st.download_button(
            "⬇️ Télécharger le rapport (PDF)", st.session_state["cpt_pdf_bytes"],
            f"rapport_compteurs_{date.today().isoformat()}.pdf", "application/pdf", key="cpt_dl_pdf",
        )

render_sidebar_footer()
