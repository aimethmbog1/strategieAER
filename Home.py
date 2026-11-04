import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from utils.data import NAVY, BLUE, GOLD, RED, GREEN, AMBER, GREY, CATEGORICAL, STATUS_COLORS
from utils.loader import get_data
from utils.ui import (
    APP_TITLE, PAGE_ICON, inject_base_style, section_title, plotly_base_layout,
    kpi_row, gauge_indicator, render_sidebar_footer, status_badge, style_map,
)
from utils.vehicules import (
    get_register as get_vehicules_register, with_age_and_reforme, besoin_acquisition_global,
    EQUIPE_NON_AFFECTEE as VEH_EQUIPE_NON_AFFECTEE, SEUIL_AGE_REFORME_DEFAUT_ANS,
)
from utils.revolving import get_register as get_revolving_register, with_derived_columns as revolving_derived
from utils.projets import get_register as get_projets_register, with_derived_columns as projets_derived
from utils.compteurs import get_cached_dataframe as get_compteurs_cache
from utils.conseiller import generate_recommendations
from utils.personnel import get_effective_roster

st.set_page_config(page_title="Vue d'ensemble — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()

data = get_data()
if data is None:
    st.stop()

# Registre RH effectif (classeur + mouvements de personnel appliqués cette
# session depuis la page Organigramme) — toujours utilisé à la place de
# data.equipes_rows / data.unassigned pour que l'app reste à jour partout.
eq_effectif, unassigned_effectif = get_effective_roster(data.equipes_rows, data.unassigned)

st.title(APP_TITLE)
st.caption(data.generated_on or "")
st.caption(
    "Cette page regroupe un résumé de **toutes les pages** de l'application, onglet par onglet, avec des "
    "visualisations (jauges, graphiques en anneau, barres) plutôt que de simples nombres. Les pages "
    "« Notes & méthodologie » (texte de méthodologie) et « Rapports » (génération de PDF à partir des "
    "indicateurs déjà résumés ici) n'ont pas de statistiques propres et ne sont donc pas reprises ci-dessous."
)

tab_general, tab_carte, tab_rh, tab_auto, tab_revolving, tab_projets, tab_compteurs, tab_conseil = st.tabs([
    "📊 Vue d'ensemble (classeur AER)",
    "🗺️ Carte, parc solaire & répartition",
    "👷 RH terrain — détail",
    "🚗 Parc automobile",
    "💰 Fonds revolving",
    "📌 Suivi de projets",
    "🔌 Statistiques compteurs",
    "🤖 Agent conseil",
])

# =====================================================================
# Onglet 1 — contenu historique de la page (inchangé) : KPI parc solaire +
# RH (issus directement du classeur AER), grille des 16 équipes, plan
# d'action et visualisations de synthèse.
# =====================================================================
with tab_general:
    # --- KPI — Parc solaire ---
    section_title("VUE D'ENSEMBLE — PARC SOLAIRE")
    ks = data.kpis_solar
    kpi_row([
        ("Sites installés", f"{int(ks.get('SITES INSTALLÉS', 0)):,}".replace(",", " "), None),
        ("Puissance totale (kWc)", f"{ks.get('PUISSANCE TOTALE (kWc)', 0):,.1f}".replace(",", " "), None),
        ("Antennes réseau solaire", str(ks.get("ANTENNES RÉSEAU SOLAIRE", "—")), None),
        ("Effectif recommandé", str(ks.get("EFFECTIF RECOMMANDÉ (total)", "—")), None),
        ("Sites / agent (moy.)", f"{ks.get('SITES / AGENT (moy.)', 0):,.1f}", None),
    ])

    st.write("")

    # --- KPI — Ressources humaines terrain ---
    section_title("VUE D'ENSEMBLE — DÉPLOIEMENT DU PERSONNEL TERRAIN (16 équipes)")
    kr = data.kpis_rh
    manque_ing = str(kr.get("MANQUE INGÉNIEURS", "—"))
    manque_tc = str(kr.get("MANQUE TECH. / CHAUFF.", "—"))
    kpi_row([
        ("Équipes constituées", str(kr.get("ÉQUIPES CONSTITUÉES", "—")), None),
        ("Postes pourvus / requis", str(kr.get("POSTES POURVUS / REQUIS", "—")), None),
        ("Total manques", str(kr.get("TOTAL MANQUES", "—")), None),
        ("Personnel disponible (non affecté)", str(kr.get("PERSONNEL DISPONIBLE (non affecté)", "—")), None),
    ])
    c1, c2 = st.columns(2)
    c1.info(f"**Manque Ingénieurs :** {manque_ing}")
    c2.info(f"**Manque Technicien / Chauffeur :** {manque_tc}")

    st.write("")

    # --- Grille de statut des 16 équipes + Plan d'action ---
    col_grid, col_donut = st.columns([2.1, 1])

    with col_grid:
        section_title("STATUT DES 16 ÉQUIPES")
        grid = data.grid.copy()
        if not grid.empty:
            role_cols = [c for c in grid.columns if c not in ("Équipe (antenne — zone)", "Statut équipe")]
            filt_statut = st.multiselect(
                "Filtrer par statut d'équipe", options=["Complète", "Partielle", "Critique"],
                default=["Complète", "Partielle", "Critique"], key="grid_filter",
            )
            view = grid[grid["Statut équipe"].isin(filt_statut)] if "Statut équipe" in grid else grid

            def style_ok(v):
                if v == "OK":
                    return f"background-color:#D9EAD3;color:{GREEN};font-weight:600;text-align:center"
                if v == "—":
                    return f"background-color:#F8D7DA;color:{RED};font-weight:600;text-align:center"
                return "text-align:center"

            def style_statut(v):
                color = STATUS_COLORS.get(v, "#666")
                return f"background-color:{color}22;color:{color};font-weight:700;text-align:center"

            styler = style_map(view.style, style_ok, subset=[c for c in role_cols if c != "Statut équipe"])
            if "Statut équipe" in view.columns:
                styler = style_map(styler, style_statut, subset=["Statut équipe"])
            st.dataframe(styler, width="stretch", hide_index=True, height=420)
        else:
            st.warning("Grille introuvable dans ce classeur.")

    with col_donut:
        section_title("TAUX DE COMPLÉTUDE")
        if not grid.empty and "Statut équipe" in grid.columns:
            counts = grid["Statut équipe"].value_counts().reindex(["Complète", "Partielle", "Critique"]).fillna(0)
            fig = go.Figure(data=[go.Pie(
                labels=counts.index, values=counts.values, hole=0.55,
                marker=dict(colors=[STATUS_COLORS[k] for k in counts.index]),
                textinfo="label+percent", sort=False,
            )])
            fig = plotly_base_layout(fig, height=300, legend=False)
            fig.update_layout(title="16 équipes")
            st.plotly_chart(fig, width="stretch")
            for label, val in counts.items():
                st.markdown(f"{status_badge(label)} &nbsp; **{int(val)}** équipe(s)", unsafe_allow_html=True)

    st.write("")
    section_title("PLAN D'ACTION PRIORITAIRE — RECRUTEMENT / REDÉPLOIEMENT")
    ap = data.action_plan
    if ap is not None and not ap.empty:
        min_manques = st.slider("Afficher les équipes avec au moins N postes manquants",
                                 0, int(ap["Postes manquants"].max()), 0)
        ap_view = ap[ap["Postes manquants"] >= min_manques]
        st.dataframe(ap_view, width="stretch", hide_index=True, height=380)
    else:
        st.info("Plan d'action non trouvé dans ce classeur (ajouté dans les versions récentes).")

    st.write("")

    # --- Visualisations de synthèse ---
    section_title("VISUALISATIONS")
    v1, v2 = st.columns(2)

    with v1:
        st.subheader("Manques par profil (RH terrain)")
        pt = data.profil_table
        if pt is not None and not pt.empty and "Profil" in pt.columns:
            pt2 = pt[pt["Profil"] != "TOTAL"]
            fig = px.pie(pt2, names="Profil", values="Manque", hole=0.35,
                         color="Profil", color_discrete_sequence=CATEGORICAL)
            fig.update_traces(textinfo="label+percent")
            fig = plotly_base_layout(fig, legend=False)
            st.plotly_chart(fig, width="stretch")

    with v2:
        st.subheader("Manques par antenne, par profil")
        rh = data.rh_table
        if rh is not None and not rh.empty:
            rh2 = rh[rh.iloc[:, 0] != "TOTAL (9 antennes / 16 équipes)"]
            fig = go.Figure()
            for col, color in zip(["Ingénieur manquant", "Technicien manquant", "Chauffeur manquant"],
                                   [RED, AMBER, BLUE]):
                if col in rh2.columns:
                    fig.add_bar(name=col.replace(" manquant", ""), x=rh2.iloc[:, 0], y=rh2[col],
                                marker_color=color)
            fig.update_layout(barmode="stack")
            fig = plotly_base_layout(fig)
            st.plotly_chart(fig, width="stretch")

# =====================================================================
# Onglet 2 — Carte, parc solaire & répartition (sites, antennes, régions)
# =====================================================================
with tab_carte:
    section_title("ÉLECTRIFICATION — SITES, ANTENNES & RÉPARTITION GÉOGRAPHIQUE")
    st.caption(
        "Résumé des pages « Carte d'électrification », « Parc solaire », « Répartition régionale » et "
        "« Organigramme » — toutes dérivées de la même feuille « Données sites » / « Antennes — Détail "
        "solaire » du classeur AER. Pour le détail interactif (filtres, carte, treemap, organigramme), "
        "ouvrez ces pages dans le menu de gauche."
    )
    sites = data.sites
    det = data.antennes_detail
    if sites is None or sites.empty:
        st.warning("Feuille « Données sites » introuvable ou vide.")
    else:
        dist_moy = sites["Distance au centre antenne (km)"].mean() if "Distance au centre antenne (km)" in sites else None
        kpi_row([
            ("Sites totaux", f"{len(sites):,}".replace(",", " "), None),
            ("Puissance totale (kWc)", f"{sites['Puissance (kWc)'].sum():,.0f}".replace(",", " "), None),
            ("Antennes (sites)", str(sites["Antenne proposée"].nunique()), None),
            ("Régions couvertes", str(sites["Région"].nunique()), None),
            ("Distance moy. au centre antenne (km)", f"{dist_moy:.1f}" if dist_moy is not None else "—", None),
        ])

        st.write("")
        cc1, cc2 = st.columns([1, 1.4])
        with cc1:
            phase_counts = sites["Phase"].value_counts()
            if not phase_counts.empty:
                fig = go.Figure(data=[go.Pie(
                    labels=phase_counts.index, values=phase_counts.values, hole=0.45,
                    marker=dict(colors=CATEGORICAL[: len(phase_counts)]),
                    textinfo="label+percent", sort=False,
                )])
                fig.update_layout(title="Sites par phase")
                fig = plotly_base_layout(fig, height=320, legend=True)
                st.plotly_chart(fig, width="stretch")
        with cc2:
            by_antenne = (sites.groupby("Antenne proposée", as_index=False).size()
                          .sort_values("size", ascending=False).head(8))
            fig = px.bar(by_antenne, x="size", y="Antenne proposée", orientation="h",
                         color_discrete_sequence=[BLUE], title="Sites par antenne (top 8)")
            fig = plotly_base_layout(fig, height=320, legend=False)
            fig.update_layout(xaxis_title="Sites", yaxis_title="")
            fig.update_yaxes(categoryorder="total ascending")
            st.plotly_chart(fig, width="stretch")

    if det is not None and not det.empty:
        st.write("")
        type_counts = det["Type"].value_counts() if "Type" in det.columns else pd.Series(dtype="int64")
        n_principales = int(type_counts.get("Principale", 0))
        n_annexes = len(det) - n_principales
        oc1, oc2 = st.columns([1, 1.4])
        with oc1:
            fig = go.Figure(data=[go.Pie(
                labels=["Principale", "Annexe rattachée"], values=[n_principales, n_annexes], hole=0.5,
                marker=dict(colors=[BLUE, GOLD]), textinfo="label+value", sort=False,
            )])
            fig.update_layout(title="Antennes — organigramme")
            fig = plotly_base_layout(fig, height=300, legend=False)
            st.plotly_chart(fig, width="stretch")
        with oc2:
            kpi_row([
                ("Antennes (organigramme)", str(len(det)), None),
                ("Effectif recommandé (total)", f"{int(det['Effectif total'].sum()):,}".replace(",", " "), None),
            ])
            region_source = data.synthese_region
            if region_source is not None and not region_source.empty and "Niveau" in region_source.columns:
                top_region = region_source[region_source["Niveau"] == "Sous-total région"].sort_values(
                    "Nb sites", ascending=False)
                if not top_region.empty:
                    r0 = top_region.iloc[0]
                    st.caption(
                        f"Région la mieux couverte (nombre de sites) : **{r0['Région']}** — "
                        f"{int(r0['Nb sites'])} site(s), {r0['Puissance totale (kWc)']:,.0f} kWc."
                        .replace(",", " ")
                    )

# =====================================================================
# Onglet 3 — RH terrain, détail par poste-type (complète, sans dupliquer,
# les KPI du classeur de l'onglet « Vue d'ensemble »)
# =====================================================================
with tab_rh:
    section_title("RH TERRAIN — DÉTAIL PAR POSTE-TYPE")
    st.caption(
        "Reprend exactement le calcul de la page « Équipes terrain » (16 équipes × 4 postes-types : "
        "Ingénieur, Technicien 1, Technicien 2, Chauffeur) — un angle plus fin, mais jamais contradictoire "
        "avec les KPI globaux du classeur affichés dans l'onglet « Vue d'ensemble ». Reflète les mouvements "
        "de personnel appliqués cette session depuis la page « Organigramme »."
    )
    eq = eq_effectif
    if eq is None or eq.empty:
        st.warning("Feuille « Données - Équipes » introuvable ou vide.")
    else:
        STANDARD_ROLES = ["Ingénieur", "Technicien 1", "Technicien 2", "Chauffeur"]
        standard = eq[eq["Rôle"].isin(STANDARD_ROLES)]
        extra = eq[~eq["Rôle"].isin(STANDARD_ROLES)]
        total = len(standard)
        ok = int((standard["Statut"] == "OK").sum())
        manque = int((standard["Statut"] == "MANQUE").sum())
        taux = (ok / total * 100) if total else 0

        rc1, rc2 = st.columns([1, 1.4])
        with rc1:
            fig = gauge_indicator(
                taux, "Taux de couverture des postes-types", low_threshold=50, high_threshold=85,
            )
            st.plotly_chart(fig, width="stretch")
        with rc2:
            fig = go.Figure(data=[go.Pie(
                labels=["Pourvus", "Manquants"], values=[ok, manque], hole=0.5,
                marker=dict(colors=[GREEN, RED]), textinfo="label+value", sort=False,
            )])
            fig.update_layout(title="Postes-types — pourvus vs manquants")
            fig = plotly_base_layout(fig, height=320, legend=False)
            st.plotly_chart(fig, width="stretch")

        unassigned = unassigned_effectif
        n_unassigned = 0 if unassigned is None else len(unassigned)
        kpi_row([
            ("Postes-types suivis (16 équipes × 4)", str(total), None),
            ("Personnel additionnel (hors profil-type)", str(len(extra)), None),
            ("Personnel non affecté à une équipe", str(n_unassigned), None),
        ])

# =====================================================================
# Onglet 4 — Parc automobile (véhicules, chauffeurs, réforme, acquisition)
# =====================================================================
with tab_auto:
    section_title("PARC AUTOMOBILE — VÉHICULES, CHAUFFEURS & RÉFORME")
    st.caption(
        "Résumé de la page « Parc automobile ». Logique d'acquisition adoptée : un véhicule par chauffeur "
        "réel (antenne par antenne, en rapprochement avec la répartition des équipes de terrain) + une "
        "réserve fixe de véhicules pour l'approvisionnement et la coordination, une seule fois pour toute "
        "la structure. Le registre n'est pas persistant d'une session à l'autre — voir cette page pour le "
        "détail et les actions d'affectation."
    )
    veh_register = get_vehicules_register()
    if veh_register.empty:
        st.info("Aucun véhicule dans le registre pour l'instant.")
    else:
        n_total = len(veh_register)
        n_affectes = int((veh_register["Équipe affectée"] != VEH_EQUIPE_NON_AFFECTEE).sum())
        view_age = with_age_and_reforme(veh_register, SEUIL_AGE_REFORME_DEFAUT_ANS)
        glob = besoin_acquisition_global(veh_register, eq_effectif)

        ac1, ac2 = st.columns([1, 1.4])
        with ac1:
            fig = gauge_indicator(
                glob["taux_couverture"], "Couverture du besoin total (chauffeurs + réserve)",
                low_threshold=50, high_threshold=90,
            )
            st.plotly_chart(fig, width="stretch")
        with ac2:
            kpi_row([
                ("Véhicules au total", str(n_total), None),
                ("Affectés à une équipe", str(n_affectes), None),
                ("Besoin net d'acquisition", str(glob["besoin_net_total"]), None),
            ])
            st.caption(
                f"Besoin brut total (chauffeurs réels + {glob['reserve_appro_coordination']} véhicule(s) de "
                f"réserve appro/coordination pour toute la structure) : **{glob['besoin_brut_total']}**. "
                f"{glob['pool_non_affecte']} véhicule(s) non affecté(s) mobilisable(s) par redéploiement."
            )

        st.write("")
        bc1, bc2 = st.columns(2)
        with bc1:
            fig = go.Figure(data=[go.Pie(
                labels=["Affectés", "Non affectés"], values=[n_affectes, n_total - n_affectes], hole=0.5,
                marker=dict(colors=[BLUE, GREY]), textinfo="label+value", sort=False,
            )])
            fig.update_layout(title="Affectation du parc")
            fig = plotly_base_layout(fig, height=300, legend=False)
            st.plotly_chart(fig, width="stretch")
        with bc2:
            statut_counts = view_age["Statut réforme"].value_counts()
            colors_reforme = {"OK": GREEN, "À surveiller (≤ 12 mois)": AMBER,
                               "Échéance dépassée": RED, "Non calculable (année inconnue)": GREY}
            fig = go.Figure(data=[go.Pie(
                labels=statut_counts.index, values=statut_counts.values, hole=0.5,
                marker=dict(colors=[colors_reforme.get(s, GREY) for s in statut_counts.index]),
                textinfo="percent", sort=False,
            )])
            fig.update_layout(title="Échéances de réforme")
            fig = plotly_base_layout(fig, height=300, legend=True)
            st.plotly_chart(fig, width="stretch")

        besoins_acq = glob["besoins_par_antenne"]
        if not besoins_acq.empty:
            besoin_affiche = besoins_acq[besoins_acq["Besoin d'acquisition (1 chauffeur = 1 véhicule)"] > 0]
            if not besoin_affiche.empty:
                fig = px.bar(
                    besoin_affiche.sort_values("Besoin d'acquisition (1 chauffeur = 1 véhicule)", ascending=False),
                    x="Antenne (RH)", y="Besoin d'acquisition (1 chauffeur = 1 véhicule)",
                    color_discrete_sequence=[RED], title="Besoin par antenne (hors réserve appro/coordination)",
                )
                fig = plotly_base_layout(fig, legend=False, height=320)
                fig.update_layout(yaxis_title="Véhicules à acquérir", xaxis_title="")
                st.plotly_chart(fig, width="stretch")

# =====================================================================
# Onglet 5 — Fonds revolving
# =====================================================================
with tab_revolving:
    section_title("FONDS REVOLVING — DOSSIERS DE RACCORDEMENT")
    st.caption(
        "Résumé de la page « Fonds revolving ». Le registre démarre vide et n'est alimenté que par ce qui "
        "est saisi sur cette page, sans persistance entre deux sessions."
    )
    revolving_view = revolving_derived(get_revolving_register())
    if revolving_view.empty:
        st.info("Aucun dossier saisi pour l'instant cette session — voir « Fonds revolving » pour en ajouter.")
    else:
        total_cout = revolving_view["Coût total du raccordement (FCFA)"].sum()
        total_a_rembourser = revolving_view["Montant à rembourser (FCFA)"].sum()
        total_rembourse = revolving_view["Montant remboursé à ce jour (FCFA)"].sum()
        total_solde = revolving_view["Solde restant dû (FCFA)"].sum()
        taux_global = (total_rembourse / total_a_rembourser * 100) if total_a_rembourser else 0

        vc1, vc2 = st.columns([1, 1.4])
        with vc1:
            fig = gauge_indicator(taux_global, "Taux de recouvrement", low_threshold=30, high_threshold=70)
            st.plotly_chart(fig, width="stretch")
        with vc2:
            counts = revolving_view["Statut"].value_counts()
            colors_map = {"En cours": BLUE, "Soldé": GREEN, "En retard": AMBER, "Litige": RED}
            fig = go.Figure(data=[go.Pie(
                labels=counts.index, values=counts.values, hole=0.5,
                marker=dict(colors=[colors_map.get(s, GREY) for s in counts.index]),
                textinfo="label+percent", sort=False,
            )])
            fig.update_layout(title="Dossiers par statut")
            fig = plotly_base_layout(fig, height=320, legend=False)
            st.plotly_chart(fig, width="stretch")

        kpi_row([
            ("Dossiers", str(len(revolving_view)), None),
            ("Total engagé (FCFA)", f"{total_cout:,.0f}".replace(",", " "), None),
            ("Solde restant dû (FCFA)", f"{total_solde:,.0f}".replace(",", " "), None),
        ])

# =====================================================================
# Onglet 6 — Suivi de projets
# =====================================================================
with tab_projets:
    section_title("SUIVI DE PROJETS — AVANCEMENT & PRIORITÉS")
    st.caption(
        "Résumé de la page « Suivi de projets ». Le registre démarre vide et n'est alimenté que par ce qui "
        "est saisi sur cette page — l'absence de projet suspendu ne veut pas dire « tout va bien », "
        "seulement « rien n'a encore été renseigné »."
    )
    projets_view = projets_derived(get_projets_register())
    if projets_view.empty:
        st.info("Aucun projet saisi pour l'instant cette session — voir « Suivi de projets » pour en ajouter.")
    else:
        STATUTS_PROJET_ORDER = ["Planifié", "En cours", "Suspendu", "Repris", "Terminé"]
        colors_map_prj = {"Planifié": GOLD, "En cours": BLUE, "Suspendu": RED, "Repris": AMBER, "Terminé": GREEN}

        pc1, pc2 = st.columns([1, 1.4])
        with pc1:
            counts = projets_view["Statut"].value_counts().reindex(STATUTS_PROJET_ORDER).fillna(0)
            fig = go.Figure(data=[go.Pie(
                labels=counts.index, values=counts.values, hole=0.5,
                marker=dict(colors=[colors_map_prj.get(s, GREY) for s in counts.index]),
                textinfo="label+percent", sort=False,
            )])
            fig.update_layout(title="Projets par statut")
            fig = plotly_base_layout(fig, height=320, legend=False)
            st.plotly_chart(fig, width="stretch")
        with pc2:
            by_region = projets_view.groupby("Région", as_index=False).size().sort_values("size", ascending=False)
            REGIONS_PRIORITAIRES = ["Nord-Ouest", "Sud-Ouest", "Extrême-Nord"]
            by_region["Prioritaire"] = by_region["Région"].isin(REGIONS_PRIORITAIRES)
            fig = px.bar(by_region, x="Région", y="size", color="Prioritaire",
                         color_discrete_map={True: RED, False: NAVY},
                         title="Projets par région (rouge = NOSO / Extrême-Nord)")
            fig = plotly_base_layout(fig, height=320, legend=False)
            fig.update_layout(yaxis_title="Projets", xaxis_title="")
            st.plotly_chart(fig, width="stretch")

        n_prioritaire_bloque = int(((projets_view["Région prioritaire (NOSO / Extrême-Nord)"] == "Oui") &
                                     (projets_view["Statut"].isin(["Planifié", "Suspendu"]))).sum())
        kpi_row([
            ("Projets suivis", str(len(projets_view)), None),
            ("En cours", str(int((projets_view["Statut"] == "En cours").sum())), None),
            ("Prioritaires à relancer (NOSO / Extrême-Nord)", str(n_prioritaire_bloque), None),
        ])

# =====================================================================
# Onglet 7 — Statistiques compteurs (si des fichiers ont été déposés)
# =====================================================================
with tab_compteurs:
    section_title("COMPTEURS — ABONNÉS INSTALLÉS")
    st.caption(
        "Résumé de la page « Statistiques des compteurs ». Cette page lit ses propres fichiers (export "
        "Holley), déposés indépendamment du classeur AER et gardés en mémoire pour la durée de la session "
        "uniquement — ce résumé n'apparaît donc qu'après un premier dépôt de fichiers sur cette page."
    )
    cpt_df = get_compteurs_cache()
    if cpt_df is None or cpt_df.empty:
        st.info(
            "Aucun fichier de compteurs déposé pour l'instant cette session — voir « Statistiques des "
            "compteurs » pour en déposer. Rien n'est conservé d'une session à l'autre."
        )
    else:
        total = len(cpt_df)
        nb_localites = cpt_df["localite"].nunique() if "localite" in cpt_df else 0
        derniere_periode = cpt_df["periode"].max() if "periode" in cpt_df else None
        nb_solaire = int(cpt_df["solaire"].sum()) if "solaire" in cpt_df else 0
        taux_solaire = (nb_solaire / total * 100) if total else 0

        qc1, qc2 = st.columns([1, 1.4])
        with qc1:
            fig = gauge_indicator(taux_solaire, "Part de compteurs solaires", low_threshold=25, high_threshold=60,
                                   low_color=GREY, mid_color=AMBER, high_color=GOLD)
            st.plotly_chart(fig, width="stretch")
        with qc2:
            top_loc = cpt_df["localite"].value_counts().head(8).reset_index()
            top_loc.columns = ["Localité", "Compteurs"]
            fig = px.bar(top_loc.sort_values("Compteurs"), x="Compteurs", y="Localité", orientation="h",
                         color_discrete_sequence=[NAVY], title="Top 8 localités équipées")
            fig = plotly_base_layout(fig, height=320, legend=False)
            st.plotly_chart(fig, width="stretch")

        kpi_row([
            ("Compteurs installés", f"{total:,}".replace(",", " "), None),
            ("Localités couvertes", str(nb_localites), None),
            ("Dernière période", derniere_periode.strftime("%m/%Y") if pd.notna(derniere_periode) else "—", None),
        ])

# =====================================================================
# Onglet 8 — Agent conseil (synthèse des recommandations)
# =====================================================================
with tab_conseil:
    section_title("AGENT CONSEIL — SYNTHÈSE DES RECOMMANDATIONS")
    st.caption(
        "Résumé de la page « Agent conseil » — moteur de règles déterministe, jamais une IA générative. "
        "Les recommandations liées au Suivi de projets et au Fonds revolving ne portent que sur ce qui a "
        "été saisi sur ces pages cette session."
    )
    projets_view2 = projets_derived(get_projets_register())
    revolving_view2 = revolving_derived(get_revolving_register())
    recommandations = generate_recommendations(data, projets_view2, revolving_view2)
    n_haute = sum(1 for r in recommandations if r["priorite"] == "Haute")
    n_moyenne = sum(1 for r in recommandations if r["priorite"] == "Moyenne")
    n_info = sum(1 for r in recommandations if r["priorite"] == "Info")

    kc1, kc2 = st.columns([1, 1.4])
    with kc1:
        fig = go.Figure(data=[go.Pie(
            labels=["Haute", "Moyenne", "Info"], values=[n_haute, n_moyenne, n_info], hole=0.5,
            marker=dict(colors=[RED, AMBER, BLUE]), textinfo="label+value", sort=False,
        )])
        fig.update_layout(title="Recommandations par priorité")
        fig = plotly_base_layout(fig, height=300, legend=False)
        st.plotly_chart(fig, width="stretch")
    with kc2:
        if recommandations:
            by_cat = pd.DataFrame(recommandations)["categorie"].value_counts().reset_index()
            by_cat.columns = ["Catégorie", "Nombre"]
            fig = px.bar(by_cat.sort_values("Nombre"), x="Nombre", y="Catégorie", orientation="h",
                         color_discrete_sequence=[NAVY], title="Recommandations par catégorie")
            fig = plotly_base_layout(fig, height=300, legend=False)
            st.plotly_chart(fig, width="stretch")
        kpi_row([("Recommandations totales", str(len(recommandations)), None)])
    if n_haute:
        st.warning(f"⚠️ {n_haute} recommandation(s) de priorité haute — voir « Agent conseil » pour le détail.")

render_sidebar_footer(data.generated_on)
