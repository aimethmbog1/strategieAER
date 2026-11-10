"""Écrans GMAO de la page Parc solaire : import des journaux et tableau de bord de maintenance."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from . import gmao as g
from .data import BLUE, GOLD, GREY, NAVY, RED
from .storage import charger, mettre_a_jour
from .ui import kpi_row, plotly_base_layout

FICHIER_INTEGRE = Path(__file__).resolve().parent.parent / "data" / "gmao_journaux.xlsx"
TABLES = {"defauts": g.REG_DEFAUTS, "statuts": g.REG_STATUTS, "inspections": g.REG_INSPECTIONS,
          "affectations": g.REG_AFFECTATIONS}


def _n(x, d=0):
    if x is None or pd.isna(x):
        return "—"
    return f"{x:,.{d}f}".replace(",", " ").replace(".", ",")


def _fig(fig, legende_bas=False, **kw):
    fig = plotly_base_layout(fig, **kw)
    fig.update_layout(separators=", ")
    if legende_bas:
        fig.update_layout(legend=dict(orientation="h", y=-0.12, x=0.5, xanchor="center"), margin=dict(t=50))
    return fig


# ------------------------------------------------------------------ données
def charger_tables() -> dict[str, pd.DataFrame]:
    """Tables GMAO de la base ; au premier usage, versement des journaux intégrés à l'application."""
    if "_gmao_tables" in st.session_state:
        return st.session_state["_gmao_tables"]
    t = {k: charger(r) for k, r in TABLES.items()}
    if (t["defauts"] is None or t["defauts"].empty) and FICHIER_INTEGRE.exists():
        xls = pd.ExcelFile(FICHIER_INTEGRE)
        for k, r in TABLES.items():
            if k in xls.sheet_names:
                t[k] = pd.read_excel(xls, sheet_name=k)
                mettre_a_jour(r, t[k], f"journaux de maintenance 2025-2026 intégrés ({len(t[k])} lignes)")
    t = {k: (v if v is not None else pd.DataFrame()) for k, v in t.items()}
    st.session_state["_gmao_tables"] = t
    return t


def enregistrer_import(nouveaux: dict[str, pd.DataFrame]) -> list[str]:
    t = charger_tables()
    faits = []
    for k, r in TABLES.items():
        if k in nouveaux and not nouveaux[k].empty:
            t[k] = g.fusionner(t.get(k), nouveaux[k], "source" if k == "defauts" else "annee")
            mettre_a_jour(r, t[k], f"import de journal — {len(nouveaux[k])} ligne(s) ({k})")
            faits.append(f"{k} : {len(nouveaux[k])}")
    st.session_state["_gmao_tables"] = t
    return faits


def classes_sites(ref_sites: pd.DataFrame) -> pd.Series | None:
    """Classe d'exploitation de chaque centrale du référentiel (index site_id), d'après le dernier journal."""
    s = g.statuts_courants(charger_tables().get("statuts"))
    if s.empty:
        return None
    m = dict(zip(s["cle_site"], s["classe"]))
    return pd.Series(ref_sites["Nom du site"].map(g.cle).map(m).values, index=ref_sites["site_id"])


# ------------------------------------------------------------------ import
def ecran_import():
    t = charger_tables()
    st.markdown("**Journaux de maintenance enregistrés dans la base**")
    d = t.get("defauts")
    if d is not None and not d.empty:
        resume = d.groupby("source").agg(Défauts=("site", "size"), Sites=("site", "nunique"),
                                         Du=("date_incident", "min"), Au=("date_incident", "max")).reset_index()
        resume["Du"] = pd.to_datetime(resume["Du"]).dt.strftime("%d/%m/%Y")
        resume["Au"] = pd.to_datetime(resume["Au"]).dt.strftime("%d/%m/%Y")
        st.dataframe(resume.rename(columns={"source": "Journal"}), hide_index=True, width="stretch")
        stt = t.get("statuts")
        st.caption(f"États de fonctionnement : {len(stt) if stt is not None else 0} ligne(s) · inspections : "
                   f"{len(t.get('inspections', []))} · affectations site / zone / responsable : {len(t.get('affectations', []))}.")
    else:
        st.info("Aucun journal enregistré.")
    st.markdown("**Ajouter ou mettre à jour un journal**")
    fichiers = st.file_uploader("Classeur « Maintenance log followup » (.xlsx)", type=["xlsx"], accept_multiple_files=True,
                                key="gmao_upload",
                                help="Feuilles lues : « Toutes les Défauts », « Status 350 localite », « TEMPS DE "
                                     "FONTIONNEMENT », « Inspection Checklist », « Repartition ». Un journal de même année "
                                     "remplace l'ancien (l'année est lue dans le nom du fichier).")
    if fichiers and st.button("📥 Importer dans la base", type="primary", key="gmao_import_btn"):
        tout = {}
        for f in fichiers:
            try:
                for k, v in g.lire_journal(f.getvalue(), f.name).items():
                    tout[k] = pd.concat([tout.get(k, pd.DataFrame()), v], ignore_index=True)
            except Exception as exc:  # noqa: BLE001
                st.error(f"{f.name} : {exc}")
        if tout:
            faits = enregistrer_import(tout)
            st.success("Import enregistré — " + " · ".join(faits))
            st.rerun()


# ------------------------------------------------------------------ tableau de bord
def tableau_de_bord(reg_saisies: pd.DataFrame, ref_sites: pd.DataFrame):
    t = charger_tables()
    base = pd.concat([t.get("defauts", pd.DataFrame()), g.depuis_saisies(reg_saisies)], ignore_index=True)
    if base.empty:
        st.info("Aucun défaut enregistré : importe un journal de maintenance ou saisis des pannes.")
        return
    from .maintenance import maintenant
    auj = pd.Timestamp(maintenant()).normalize()
    d0 = g.ajouter_calculs(g.normaliser_defauts(base), auj)
    statuts = g.statuts_courants(t.get("statuts"))
    affect = t.get("affectations")

    # ---------------- filtres
    with st.expander("🔎 Filtres — s'appliquent à tout le tableau de bord", expanded=True):
        c = st.columns(4)
        dates = d0["date_incident"].dropna()
        dmin, dmax = dates.min().date(), dates.max().date()
        periode = c[0].date_input("Période (date de l'incident)", (dmin, dmax), min_value=dmin, max_value=dmax,
                                  format="DD/MM/YYYY", key="gm_per")
        sources = c[1].multiselect("Journal", sorted(d0["source"].dropna().unique()), key="gm_src")
        phases = c[2].multiselect("Phase", sorted(d0["phase"].dropna().unique()), key="gm_ph")
        regions = c[3].multiselect("Région", sorted(d0["region"].dropna().unique()), key="gm_reg")
        c = st.columns(4)
        cats = c[0].multiselect("Catégorie de défaut", sorted(d0["categorie"].dropna().unique()), key="gm_cat")
        prios = c[1].multiselect("Priorité", sorted(d0["priorite"].dropna().unique()), key="gm_prio")
        res = c[2].multiselect("Résultat", sorted(d0["resultat"].dropna().unique()), key="gm_res")
        zones = c[3].multiselect("Zone / responsable", sorted(affect["responsable"].dropna().unique())
                                 if affect is not None and not affect.empty else [], key="gm_resp")
        c = st.columns([2, 1, 1])
        site_q = c[0].text_input("Centrale (recherche)", key="gm_site")
        sans_date = c[1].checkbox("Inclure les défauts sans date", value=True, key="gm_nodate")
        exclure_2025 = c[2].checkbox("Exclure les « en attente » 2025 non mis à jour", value=False, key="gm_ex25",
                                     help="Les défauts du journal 2025 encore « Pending » n'ont pas été mis à jour depuis : "
                                          "beaucoup ont probablement été traités. Coche pour les retirer du backlog.")
    d = d0.copy()
    if isinstance(periode, tuple) and len(periode) == 2:
        m = d["date_incident"].between(pd.Timestamp(periode[0]), pd.Timestamp(periode[1]) + pd.Timedelta(days=1))
        d = d[m | (d["date_incident"].isna() & sans_date)]
    for col, val in (("source", sources), ("phase", phases), ("region", regions), ("categorie", cats),
                     ("priorite", prios), ("resultat", res)):
        if val:
            d = d[d[col].isin(val)]
    if zones:
        sites_z = set(affect.loc[affect["responsable"].isin(zones), "site"].map(g.cle))
        d = d[d["cle_site"].isin(sites_z)]
    if site_q:
        d = d[d["site"].str.contains(site_q, case=False, na=False)]
    if exclure_2025:
        d = d[~((d["source"] == "Journal 2025") & (d["resultat"] != "Clôturé"))]
    if d.empty:
        st.warning("Aucun défaut ne correspond aux filtres.")
        return

    k = g.kpis(d)
    kpi_row([
        ("Défauts", _n(k["defauts"]), None),
        ("Centrales concernées", _n(k["sites"]), None),
        ("Taux de clôture", f"{_n(k['taux_cloture'], 1)} %", None),
        ("Backlog (en attente)", _n(k["backlog"]), f"dont {_n(k['en_retard'])} hors délai"),
        ("MTTR moyen / médian", f"{_n(k['mttr_moy'], 1)} j / {_n(k['mttr_med'], 0)} j", None),
    ])
    kpi_row([
        ("Respect des délais prévus", f"{_n(k['respect_delais'], 1)} %", None),
        ("Défauts critiques / urgents", _n(k["critiques"]), None),
        ("Site trouvé à l'arrêt", f"{_n(k['arret_arrivee'], 1)} %", None),
        ("Défauts par centrale", _n(k["defauts"] / k["sites"], 1) if k["sites"] else "—", None),
        ("Délais incohérents corrigés", _n(int(d["delai_incoherent"].fillna(False).sum())), None),
    ])
    st.caption("MTTR : délai moyen entre l'incident et sa clôture (défauts clôturés). Backlog hors délai : défauts en attente "
               "depuis plus longtemps que le nombre de jours prévu. Respect des délais : défauts clôturés dans le délai prévu.")

    onglets = st.tabs(["🟢 Disponibilité du parc", "⚠️ Défaillances", "🏭 Centrales", "⏱️ Délais & backlog",
                       "🔩 Pièces & matériel", "👷 Zones & équipes", "🧪 Qualité des données", "📋 Données"])

    # ---- 1. disponibilité
    with onglets[0]:
        if statuts.empty:
            st.info("Aucun état de fonctionnement importé.")
        else:
            s = statuts.copy()
            if phases:
                s = s[s["phase"].isin(phases)]
            if regions:
                s = s[s["region"].isin(regions)]
            st.markdown(f"**État de fonctionnement des centrales suivies dans le journal {int(s['annee'].max())}** "
                        f"({len(s)} centrales, Phases 1 et 2 — la Phase 3 n'est pas couverte par ces journaux)")
            par = pd.crosstab(s["phase"], s["classe"], margins=True, margins_name="Total").reindex(
                columns=[c for c in g.CLASSES if c in s["classe"].unique()] + ["Total"])
            pw = s.groupby("classe")["puissance_kwc"].sum()
            c1, c2 = st.columns([3, 2])
            with c1:
                st.dataframe(par, width="stretch")
                tot_kw = s["puissance_kwc"].sum()
                st.caption(" · ".join(f"{cl} : {_n(pw.get(cl, 0), 1)} kWc ({_n(pw.get(cl, 0) / tot_kw * 100, 1)} %)"
                                      for cl in g.CLASSES if cl in pw.index))
            with c2:
                fig = px.pie(s, names="classe", hole=0.45, color="classe",
                             color_discrete_map={"Fonctionnelle (H24)": NAVY, "Fonctionnement partiel": GOLD,
                                                 "À l'arrêt": RED, "Non renseigné": GREY})
                st.plotly_chart(_fig(fig, legende_bas=True, height=320), width="stretch")
            reg_tab = pd.crosstab(s["region"], s["classe"])
            reg_tab["Taux en service (%)"] = ((reg_tab.get("Fonctionnelle (H24)", 0) + reg_tab.get("Fonctionnement partiel", 0))
                                              / reg_tab.sum(axis=1) * 100).round(1)
            st.markdown("**Par région**")
            st.dataframe(reg_tab.sort_values("Taux en service (%)"), width="stretch")
            arr = s[s["classe"] == "À l'arrêt"]
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"**Causes d'arrêt** ({len(arr)} centrales)")
                causes = arr["causes"].fillna("Non précisée").value_counts().rename_axis("Cause").reset_index(name="Centrales")
                fig = px.bar(causes.head(12), x="Centrales", y="Cause", orientation="h", color_discrete_sequence=[RED])
                fig.update_yaxes(categoryorder="total ascending")
                st.plotly_chart(_fig(fig, height=60 + 30 * min(len(causes), 12), legend=False), width="stretch")
            with c2:
                if "plage_horaire" in s:
                    st.markdown("**Plages horaires paramétrées (centrales en service)**")
                    ph = s[s["classe"] != "À l'arrêt"]["plage_horaire"].fillna("Non renseignée").astype(str).str.strip()
                    ph = ph.replace({"Aucun": "Aucune restriction (H24)"}).value_counts().rename_axis("Plage").reset_index(name="Centrales")
                    st.dataframe(ph, hide_index=True, width="stretch", height=300)
            st.markdown("**Centrales à l'arrêt**")
            st.dataframe(arr[["site", "phase", "region", "puissance_kwc", "etat", "causes"]].rename(columns={
                "site": "Centrale", "phase": "Phase", "region": "Région", "puissance_kwc": "Puissance (kWc)",
                "etat": "État", "causes": "Causes"}).sort_values("Puissance (kWc)", ascending=False),
                hide_index=True, width="stretch", height=320)

    # ---- 2. défaillances
    with onglets[1]:
        c1, c2 = st.columns(2)
        for col, titre, cible in (("categorie", "Pareto des catégories de défaut", c1), ("materiel", "Pareto du matériel affecté", c2)):
            p = g.pareto(d, col)
            fig = go.Figure()
            fig.add_bar(x=p[col], y=p["Défauts"], name="Défauts", marker_color=NAVY)
            fig.add_scatter(x=p[col], y=p["% cumulé"], name="% cumulé", yaxis="y2", mode="lines+markers",
                            line=dict(color=GOLD, width=3))
            fig.update_layout(yaxis2=dict(overlaying="y", side="right", range=[0, 105], ticksuffix=" %"), title=titre)
            with cible:
                st.plotly_chart(_fig(fig, height=400), width="stretch")
        c1, c2, c3 = st.columns(3)
        with c1:
            fig = px.pie(d, names="priorite", hole=0.45, title="Répartition par priorité",
                         color_discrete_sequence=[RED, NAVY, BLUE, GOLD, GREY])
            st.plotly_chart(_fig(fig, legende_bas=True, height=340), width="stretch")
        with c2:
            fig = px.pie(d, names="etat_arrivee", hole=0.45, title="État du site à l'arrivée",
                         color_discrete_sequence=[NAVY, RED, GREY])
            st.plotly_chart(_fig(fig, legende_bas=True, height=340), width="stretch")
        with c3:
            fig = px.pie(d, names="phase", hole=0.45, title="Défauts par phase", color_discrete_sequence=[NAVY, GOLD, BLUE])
            st.plotly_chart(_fig(fig, legende_bas=True, height=340), width="stretch")
        st.markdown("**Catégories de défaut par région**")
        ht = pd.crosstab(d["categorie"], d["region"].fillna("Non renseignée"))
        fig = px.imshow(ht, text_auto=True, aspect="auto", color_continuous_scale="Blues")
        st.plotly_chart(_fig(fig, height=80 + 26 * len(ht), legend=False), width="stretch")

    # ---- 3. centrales
    with onglets[2]:
        pc = g.par_centrale(d, statuts, affect, auj)
        st.markdown("**Fiabilité par centrale** — MTBF : intervalle moyen entre deux jours d'incident ; à comparer entre "
                    "centrales de même technologie.")
        st.dataframe(pc, hide_index=True, width="stretch", height=420,
                     column_config={"Premier défaut": st.column_config.DateColumn(format="DD/MM/YYYY"),
                                    "Dernier défaut": st.column_config.DateColumn(format="DD/MM/YYYY")})
        st.download_button("⬇️ Exporter (CSV)", pc.to_csv(index=False, sep=";").encode("utf-8-sig"),
                           "gmao_fiabilite_centrales.csv", "text/csv", key="gm_dl_pc")
        c1, c2 = st.columns(2)
        with c1:
            top = pc.head(20)
            fig = px.bar(top, x="Défauts", y="Centrale", orientation="h", color="Critiques",
                         color_continuous_scale="Reds", title="20 centrales les plus défaillantes")
            fig.update_yaxes(categoryorder="total ascending")
            st.plotly_chart(_fig(fig, height=560), width="stretch")
        with c2:
            st.markdown("**Défaillances récurrentes** (même matériel, même centrale, au moins 2 fois)")
            st.dataframe(g.recurrences(d), hide_index=True, width="stretch", height=520,
                         column_config={"Premier": st.column_config.DateColumn(format="DD/MM/YYYY"),
                                        "Dernier": st.column_config.DateColumn(format="DD/MM/YYYY")})

    # ---- 4. délais & backlog
    with onglets[3]:
        tr = g.tendance(d)
        # on démarre au premier mois significatif (quelques dates isolées très anciennes écrasent l'axe)
        significatif = tr[tr["Défauts déclarés"] >= 3]
        if not significatif.empty:
            tr = tr[tr["Mois"] >= significatif["Mois"].min()]
        fig = go.Figure()
        fig.add_bar(x=tr["Mois"], y=tr["Défauts déclarés"], name="Déclarés", marker_color=NAVY)
        fig.add_bar(x=tr["Mois"], y=tr["Défauts clôturés"], name="Clôturés", marker_color=GOLD)
        fig.add_scatter(x=tr["Mois"], y=tr["Backlog cumulé"], name="Backlog cumulé", yaxis="y2", mode="lines",
                        line=dict(color=RED, width=3))
        fig.update_layout(barmode="group", yaxis2=dict(overlaying="y", side="right"),
                          title="Défauts déclarés et clôturés par mois, backlog cumulé")
        st.plotly_chart(_fig(fig, height=380), width="stretch")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Âge du backlog par priorité**")
            st.dataframe(g.age_backlog(d), hide_index=True, width="stretch")
        with c2:
            clos = d[(d["resultat"] == "Clôturé") & d["delai_resolution_j"].notna()]
            if not clos.empty:
                m = clos.groupby("categorie")["delai_resolution_j"].agg(["mean", "median", "count"]).round(1)
                m.columns = ["MTTR moyen (j)", "MTTR médian (j)", "Défauts clôturés"]
                st.markdown("**Délai de résolution par catégorie**")
                st.dataframe(m.sort_values("MTTR moyen (j)", ascending=False), width="stretch")
        retard = d[d["en_retard"]].sort_values("age_j", ascending=False)
        st.markdown(f"**Défauts en attente hors délai** ({len(retard)})")
        st.dataframe(retard[["site", "phase", "categorie", "materiel", "description", "priorite", "date_incident",
                             "jours_prevus", "age_j", "source"]].rename(columns={
            "site": "Centrale", "phase": "Phase", "categorie": "Catégorie", "materiel": "Matériel",
            "description": "Description", "priorite": "Priorité", "date_incident": "Incident",
            "jours_prevus": "Délai prévu (j)", "age_j": "En attente depuis (j)", "source": "Journal"}),
            hide_index=True, width="stretch", height=360,
            column_config={"Incident": st.column_config.DateColumn(format="DD/MM/YYYY")})

    # ---- 5. pièces
    with onglets[4]:
        p = g.pieces(d)
        st.markdown("**Besoins en pièces de rechange** — quantités affectées dans les défauts et quantités déjà remplacées "
                    "(câbles et lignes, comptés en mètres, sont exclus pour ne pas fausser les totaux)")
        st.dataframe(p, hide_index=True, width="stretch", height=380)
        top = p.head(15).melt(id_vars="Matériel", value_vars=["Quantité remplacée", "Reste à remplacer"],
                              var_name="Statut", value_name="Quantité")
        fig = px.bar(top, x="Quantité", y="Matériel", color="Statut", orientation="h",
                     color_discrete_map={"Quantité remplacée": NAVY, "Reste à remplacer": RED})
        fig.update_layout(barmode="stack", title="15 matériels au plus fort besoin de remplacement")
        fig.update_yaxes(categoryorder="total ascending")
        st.plotly_chart(_fig(fig, height=480), width="stretch")
        lin = d[d["lineaire"]].groupby("materiel")[["qte_affectee", "qte_remplacee"]].sum()
        if not lin.empty:
            st.markdown("**Câbles et lignes (mètres)**")
            st.dataframe(lin.rename(columns={"qte_affectee": "Affecté (m)", "qte_remplacee": "Remplacé (m)"}), width="stretch")

    # ---- 6. zones & équipes
    with onglets[5]:
        pr = g.par_responsable(d, affect)
        if pr.empty:
            st.info("Aucune affectation site / zone / responsable importée.")
        else:
            st.markdown("**Performance par zone et responsable**")
            st.dataframe(pr, hide_index=True, width="stretch")
            fig = go.Figure()
            fig.add_bar(x=pr["Responsable"], y=pr["Clôturés"], name="Clôturés", marker_color=NAVY)
            fig.add_bar(x=pr["Responsable"], y=pr["En attente"], name="En attente", marker_color=GOLD)
            fig.update_layout(barmode="stack", title="Défauts traités et en attente par responsable de zone")
            st.plotly_chart(_fig(fig, height=360), width="stretch")
        ins = t.get("inspections")
        if ins is not None and not ins.empty:
            ins = ins.copy()
            ins["date_inspection"] = pd.to_datetime(ins["date_inspection"], errors="coerce")
            couv = ins["site"].map(g.cle).nunique()
            n_suivies = len(statuts) if not statuts.empty else 350
            kpi_row([("Inspections datées", _n(len(ins)), None),
                     ("Centrales inspectées", f"{couv} / {n_suivies}", f"{_n(couv / n_suivies * 100, 1)} %"),
                     ("Dernière inspection", ins["date_inspection"].max().strftime("%d/%m/%Y"), None)])
            par_mois = ins.groupby(ins["date_inspection"].dt.to_period("M").dt.to_timestamp()).size().reset_index(name="Inspections")
            fig = px.bar(par_mois, x="date_inspection", y="Inspections", color_discrete_sequence=[BLUE],
                         labels={"date_inspection": ""}, title="Inspections par mois")
            st.plotly_chart(_fig(fig, height=280, legend=False), width="stretch")

    # ---- 7. qualité
    with onglets[6]:
        q = {
            "Défauts sans date d'incident": int(d0["date_incident"].isna().sum()),
            "Défauts sans catégorie": int((d0["categorie"] == "Non renseignée").sum()),
            "Défauts sans priorité": int((d0["priorite"] == "Non renseignée").sum()),
            "Résultat non renseigné": int((d0["resultat"] == "Non renseigné").sum()),
            "Délais de résolution incohérents (négatifs ou > 1 000 j), recalculés": int(d0["delai_incoherent"].fillna(False).sum()),
            "Clôturés sans date d'achèvement": int(((d0["resultat"] == "Clôturé") & d0["date_achevement"].isna()).sum()),
            "En attente du journal 2025 jamais mis à jour": int(((d0["source"] == "Journal 2025") & (d0["resultat"] != "Clôturé")).sum()),
            "Doublons probables (même centrale, date, matériel, description)": int(d0.duplicated(
                subset=["cle_site", "date_incident", "materiel", "description"]).sum()),
        }
        ref_cles = set(ref_sites["Nom du site"].map(g.cle))
        hors_ref = sorted(set(d0.loc[~d0["cle_site"].isin(ref_cles), "site"]))
        q["Centrales du journal absentes du référentiel des 499 sites"] = len(hors_ref)
        if not statuts.empty and "etat_feuille_temps" in statuts:
            diff = statuts[statuts["etat_feuille_temps"].notna() &
                           (statuts["etat_feuille_temps"].map(g.classe_etat) != statuts["classe"])]
            q["État différent entre « Status » et « Temps de fonctionnement »"] = len(diff)
        st.dataframe(pd.DataFrame(list(q.items()), columns=["Contrôle", "Lignes concernées"]), hide_index=True,
                     width="stretch")
        if hors_ref:
            st.caption("Noms à rapprocher du référentiel : " + ", ".join(hors_ref))
        st.caption("Les indicateurs utilisent les délais recalculés à partir des dates. Corriger les journaux sources puis "
                   "les réimporter améliore directement la fiabilité du tableau de bord.")

    # ---- 8. données
    with onglets[7]:
        cols = ["source", "site", "phase", "region", "etat_arrivee", "categorie", "materiel", "description", "mesure",
                "priorite", "resultat", "date_incident", "date_achevement", "delai_resolution_j", "jours_prevus",
                "age_j", "qte_affectee", "qte_remplacee", "code_materiel"]
        vue = d[cols].sort_values("date_incident", ascending=False)
        st.dataframe(vue, hide_index=True, width="stretch", height=460,
                     column_config={"date_incident": st.column_config.DateColumn("Incident", format="DD/MM/YYYY"),
                                    "date_achevement": st.column_config.DateColumn("Achèvement", format="DD/MM/YYYY")})
        st.caption(f"{len(vue)} défaut(s) après filtres")
        st.download_button("⬇️ Exporter la sélection (CSV)", vue.to_csv(index=False, sep=";").encode("utf-8-sig"),
                           "gmao_defauts.csv", "text/csv", key="gm_dl_all")
