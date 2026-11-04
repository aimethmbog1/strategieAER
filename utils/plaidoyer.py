"""
Dossier de plaidoyer — collecte des indicateurs sourcés, contrôles de cohérence,
textes FR/EN et génération des documents (PDF par langue + annexe Excel).

Principe : aucun chiffre n'est écrit en dur dans le dossier. Chaque indicateur est
lu dans le classeur source, un registre de l'application ou la table des
« références validées » (saisie et datée par l'utilisateur), et porte sa source,
sa date et son statut (Validé / Calculé / Provisoire / À actualiser).
"""
from __future__ import annotations

import io

import pandas as pd

from pathlib import Path

from .storage import charger

_SEED_BUDGET = Path(__file__).resolve().parent.parent / "data" / "budget_sdmse_2027.csv"
UNITES_EN = {"sites": "sites", "kWc": "kWp", "antennes": "branches", "agents": "staff", "équipes": "teams",
             "postes": "positions", "centrales": "mini-grids", "compteurs": "meters", "ménages": "households",
             "abonnés": "customers", "kWh": "kWh", "FCFA": "XAF", "projets": "projects", "dossiers": "files", "%": "%"}


def budget_registre() -> pd.DataFrame | None:
    """Registre budgétaire enregistré, ou à défaut le budget initial 2027 de la SDMSE."""
    bu = charger("budget_register")
    if bu is None and _SEED_BUDGET.exists():
        bu = pd.read_csv(_SEED_BUDGET, dtype=str).fillna("")
        bu.insert(0, "Exercice", "2027")
    return bu

AUDIENCES = {
    "Conseil d'Administration de l'AER": "AER Board of Directors",
    "Ministère de l'Eau et de l'Énergie (MINEE)": "Ministry of Water and Energy (MINEE)",
    "Services du Premier Ministre": "Prime Minister's Office",
    "Présidence de la République": "Presidency of the Republic",
    "Partenaires techniques et financiers": "Technical and financial partners",
}

# Références validées (rapports institutionnels 2026) — modifiables et datées dans la page
REFERENCES_DEFAUT = [
    ("Centrales solaires opérationnelles", "Operational solar mini-grids", 437, "centrales", "Rapport institutionnel 2026 (Phase I : 166 · Phase II : 184 · Phase III T1 : 87)"),
    ("Compteurs à prépaiement installés", "Prepaid meters installed", 8600, "compteurs", "Rapport institutionnel 2026 (Phase I : 1 347 · II : 3 981 · III : 2 873)"),
    ("Potentiel de ménages desservables", "Households that can be served", 59516, "ménages", "Rapport institutionnel 2026"),
    ("Abonnés réels (2026, partiel)", "Actual subscribers (2026, partial)", 31790, "abonnés", "Rapport institutionnel 2026"),
    ("Énergie facturée cumulée", "Cumulative energy billed", 24990851, "kWh", "Data Center AER, cumul"),
    ("Recettes cumulées (Data Center)", "Cumulative revenue (Data Center)", 2499107194, "FCFA", "Data Center AER, cumul"),
]

SECTIONS = [
    ("contexte", "1. Contexte et enjeux", "1. Context and stakes"),
    ("resultats", "2. Résultats obtenus", "2. Results achieved"),
    ("difficultes", "3. Difficultés rencontrées", "3. Challenges"),
    ("besoins", "4. Besoins et financement sollicité", "4. Needs and funding requested"),
    ("demandes", "5. Recommandations et décisions attendues", "5. Recommendations and decisions sought"),
]

TEXTES_DEFAUT = {
    "contexte": (
        "L'Agence d'Électrification Rurale met en œuvre le programme d'électrification rurale par centrales "
        "solaires photovoltaïques. Le parc suivi compte {sites} sites pour une puissance installée de {kwc} kWc, "
        "répartis entre {antennes} antennes. La pérennité de ces investissements publics dépend de la qualité de "
        "leur exploitation, de la sécurisation des recettes et de la disponibilité d'équipes qualifiées sur le terrain.",
        "The Rural Electrification Agency implements the rural electrification programme based on solar "
        "photovoltaic mini-grids. The monitored portfolio comprises {sites} sites with {kwc} kWp installed, "
        "spread across {antennes} regional branches. The sustainability of these public investments depends on "
        "sound operation, secured revenue and qualified field teams."),
    "resultats": (
        "{equipes} équipes terrain sont constituées ({pourvus} postes pourvus sur {requis}). "
        "⟨Compléter avec les résultats d'exploitation : disponibilité des centrales, abonnés actifs, recettes.⟩",
        "{equipes} field teams have been set up ({pourvus} positions filled out of {requis}). "
        "⟨Complete with operating results: mini-grid availability, active customers, revenue.⟩"),
    "difficultes": (
        "Il convient de relever un déficit de {manques} postes dans les équipes terrain, en particulier "
        "d'ingénieurs. ⟨Compléter : vieillissement des batteries de Phase I, accès aux zones prioritaires, "
        "supervision à distance, financement de la maintenance.⟩",
        "There is a shortfall of {manques} positions in field teams, particularly engineers. "
        "⟨Complete: ageing Phase I batteries, access to priority areas, remote monitoring, maintenance funding.⟩"),
    "besoins": (
        "Le budget prévisionnel inscrit au registre budgétaire s'élève à {budget} FCFA ({budget_f} FCFA de "
        "fonctionnement et {budget_i} FCFA d'investissement). ⟨Préciser les priorités et le calendrier.⟩",
        "The planned budget recorded in the budget register amounts to XAF {budget} (XAF {budget_f} operating "
        "and XAF {budget_i} investment). ⟨Specify priorities and timeline.⟩"),
    "demandes": (
        "⟨Formuler les décisions attendues de l'instance destinataire : validation budgétaire, autorisation de "
        "recrutement, appui à la sécurisation des sites, mobilisation de financements.⟩",
        "⟨State the decisions sought from the recipient body: budget approval, recruitment authorisation, "
        "support for site security, mobilisation of funding.⟩"),
}


def _fmt(x, dec=0) -> str:
    try:
        return f"{float(x):,.{dec}f}".replace(",", " ")
    except (TypeError, ValueError):
        return str(x)


def indicateurs(data, inclure_paie: bool, references: pd.DataFrame) -> pd.DataFrame:
    """Inventaire des indicateurs : FR, EN, Valeur, Unité, Source, Date, Statut."""
    L = []
    gen = (data.generated_on or "").split("—")[0].replace("Généré le", "").strip() if data else ""

    def add(fr, en, val, unite, source, date, statut):
        L.append({"Indicateur": fr, "Indicator": en, "Valeur": val, "Unité": unite, "Source": source,
                  "Date": date, "Statut": statut})

    ks = (data.kpis_solar or {}) if data else {}
    kr = (data.kpis_rh or {}) if data else {}
    if ks:
        add("Sites solaires installés", "Solar sites installed", ks.get("SITES INSTALLÉS"), "sites", "Classeur AER — Données sites", gen, "Validé")
        add("Puissance installée", "Installed capacity", ks.get("PUISSANCE TOTALE (kWc)"), "kWc", "Classeur AER — Données sites", gen, "Validé")
        add("Antennes du réseau solaire", "Solar network branches", ks.get("ANTENNES RÉSEAU SOLAIRE"), "antennes", "Classeur AER", gen, "Validé")
        add("Effectif terrain recommandé", "Recommended field staff", ks.get("EFFECTIF RECOMMANDÉ (total)"), "agents", "Classeur AER", gen, "Calculé")
    if kr:
        add("Équipes terrain constituées", "Field teams set up", kr.get("ÉQUIPES CONSTITUÉES"), "équipes", "Classeur AER — Données - Équipes", gen, "Validé")
        add("Postes pourvus / requis", "Positions filled / required", kr.get("POSTES POURVUS / REQUIS"), "postes", "Classeur AER — Données - Équipes", gen, "Validé")
        add("Postes manquants", "Vacant positions", kr.get("TOTAL MANQUES"), "postes", "Classeur AER — Données - Équipes", gen, "Validé")

    for _, r in references.iterrows():
        add(r["Indicateur"], r["Indicator"], r["Valeur"], r["Unité"], r["Source"], str(r["Date"]), r["Statut"])

    pj = charger("projets_register")
    if pj is not None and not pj.empty:
        add("Projets suivis", "Projects monitored", len(pj), "projets", "Registre de suivi de projets", "", "Provisoire")
        add("Projets à relancer (planifiés / suspendus)", "Projects to relaunch (planned / suspended)",
            int(pj["Statut"].isin(["Planifié", "Suspendu"]).sum()), "projets", "Registre de suivi de projets", "", "Provisoire")
    rv = charger("revolving_register")
    if rv is not None and not rv.empty:
        cout = pd.to_numeric(rv["Coût total du raccordement (FCFA)"], errors="coerce").fillna(0)
        init = pd.to_numeric(rv["Frais initial payé par le ménage (FCFA)"], errors="coerce").fillna(0)
        remb = pd.to_numeric(rv["Montant remboursé à ce jour (FCFA)"], errors="coerce").fillna(0)
        du = (cout - init).sum()
        add("Dossiers du fonds revolving", "Revolving fund files", len(rv), "dossiers", "Registre du fonds revolving", "", "Provisoire")
        add("Taux de recouvrement du fonds revolving", "Revolving fund recovery rate",
            round(remb.sum() / du * 100, 1) if du else 0, "%", "Registre du fonds revolving", "", "Calculé")
    sup = charger("supervision_mesures")
    if sup is not None and not sup.empty:
        sup["Date"] = pd.to_datetime(sup["Date"])
        ref = sup["Date"].max()
        der = sup.groupby("Centrale")["Date"].max()
        add("Centrales supervisées à distance", "Remotely monitored mini-grids", int(der.size), "centrales", "Imports de supervision", f"{ref:%d/%m/%Y}", "Calculé")
        add("Centrales silencieuses (> 2 jours)", "Silent mini-grids (> 2 days)", int(((ref - der).dt.days > 2).sum()), "centrales", "Imports de supervision", f"{ref:%d/%m/%Y}", "Calculé")
        add("Production supervisée", "Monitored generation", round(sup["Production (kWh)"].sum()), "kWh", "Imports de supervision",
            f"{sup['Date'].min():%d/%m/%Y} – {ref:%d/%m/%Y}", "Calculé")
    ve = charger("ventes_register")
    if ve is not None and not ve.empty:
        ve["Date"] = pd.to_datetime(ve["Date"])
        fin = ve["Date"].max()
        periode = f"{ve['Date'].min():%d/%m/%Y} – {fin:%d/%m/%Y}"
        add("Recettes des ventes importées", "Revenue from imported sales", round(pd.to_numeric(ve["Montant (FCFA)"]).sum()), "FCFA", "États de vente importés", periode, "Calculé")
        add("Compteurs actifs (achat sur 90 jours)", "Active meters (purchase within 90 days)",
            int(ve[ve["Date"] > fin - pd.Timedelta(days=90)]["Compteur"].nunique()), "compteurs", "États de vente importés", f"{fin:%d/%m/%Y}", "Calculé")
    bu = budget_registre()
    if bu is not None and not bu.empty:
        b = bu.copy()
        for c in ("Montant prévu (FCFA)", "Engagé (FCFA)", "Payé (FCFA)"):
            b[c] = pd.to_numeric(b[c], errors="coerce").fillna(0)
        ex = sorted(b["Exercice"].astype(str).unique())[-1]
        b = b[b["Exercice"].astype(str) == ex]
        add(f"Budget prévisionnel {ex} (SDMSE)", f"Planned budget {ex} (SDMSE)", round(b["Montant prévu (FCFA)"].sum()), "FCFA", "Registre budgétaire", ex, "Validé")
        add(f"dont fonctionnement {ex}", f"of which operating {ex}", round(b.loc[b["F/I"] == "F", "Montant prévu (FCFA)"].sum()), "FCFA", "Registre budgétaire", ex, "Validé")
        add(f"dont investissement {ex}", f"of which investment {ex}", round(b.loc[b["F/I"] == "I", "Montant prévu (FCFA)"].sum()), "FCFA", "Registre budgétaire", ex, "Validé")
        add(f"Taux d'engagement {ex}", f"Commitment rate {ex}",
            round(b["Engagé (FCFA)"].sum() / b["Montant prévu (FCFA)"].sum() * 100, 1) if b["Montant prévu (FCFA)"].sum() else 0,
            "%", "Registre budgétaire", ex, "Provisoire")
    if inclure_paie:
        from .paie import calculer_masse, parametres_par_defaut
        pr = charger("paie_registre")
        if pr is not None and not pr.empty:
            res, _ = calculer_masse(pr, parametres_par_defaut())
            if not res.empty:
                add("Effectif inscrit au registre de paie", "Staff on payroll register", len(res), "agents", "Registre de paie", "", "Provisoire")
                add("Coût employeur annuel (mois × 12)", "Annual employer cost (month × 12)", round(res["Coût employeur"].sum() * 12), "FCFA", "Registre de paie", "", "Provisoire")
    return pd.DataFrame(L)


def controles(ind: pd.DataFrame, en: bool = False) -> list[str]:
    """Contrôles de cohérence entre sources — à lever avant toute diffusion."""
    out = []
    def val(lib):
        s = ind.loc[ind["Indicateur"] == lib, "Valeur"]
        try:
            return float(s.iloc[0]) if len(s) else None
        except (TypeError, ValueError):
            return None
    sites, centrales = val("Sites solaires installés"), val("Centrales solaires opérationnelles")
    if sites and centrales and sites != centrales:
        out.append(f"The workbook lists {_fmt(sites)} installed sites and the validated reference {_fmt(centrales)} "
                   "operational mini-grids: explain the difference (non-operational sites, different scopes)." if en else
                   f"Le classeur compte {_fmt(sites)} sites installés, la référence validée {_fmt(centrales)} centrales "
                   "opérationnelles : préciser la différence (sites non opérationnels, périmètres distincts) dans le texte.")
    abonnes, cpt = val("Abonnés réels (2026, partiel)"), val("Compteurs à prépaiement installés")
    if abonnes and cpt and abonnes > cpt:
        out.append(f"Reported customers ({_fmt(abonnes)}) exceed installed meters ({_fmt(cpt)}): define 'customer' "
                   "(individual meters, collective connections, flat-rate) before release." if en else
                   f"Abonnés déclarés ({_fmt(abonnes)}) supérieurs aux compteurs installés ({_fmt(cpt)}) : définir "
                   "« abonné » (compteurs individuels, branchements collectifs, forfaits) avant diffusion.")
    actifs = val("Compteurs actifs (achat sur 90 jours)")
    if actifs and cpt and actifs > cpt:
        out.append("Active meters exceed the installed base: check sales imports and the reference base." if en else
                   "Compteurs actifs supérieurs au parc installé : vérifier les imports de ventes et le parc de référence.")
    for _, r in ind[ind["Statut"].isin(["À actualiser"])].iterrows():
        out.append(f"'{r['Indicator']}' is flagged 'to be updated' (date: {r['Date'] or 'not set'})." if en else
                   f"« {r['Indicateur']} » est marqué « à actualiser » (date : {r['Date'] or 'non renseignée'}).")
    return out


def valeurs_gabarit(ind: pd.DataFrame) -> dict:
    def v(lib, dec=0, defaut="⟨n.d.⟩"):
        s = ind.loc[ind["Indicateur"] == lib, "Valeur"]
        if not len(s):
            return defaut
        x = s.iloc[0]
        return _fmt(x, dec) if isinstance(x, (int, float)) else str(x)
    pr = v("Postes pourvus / requis")
    pourvus, requis = (pr.split("/") + ["⟨n.d.⟩"])[:2] if "/" in pr else ("⟨n.d.⟩", "⟨n.d.⟩")
    bud = ind[ind["Indicateur"].str.startswith("Budget prévisionnel")]
    bf = ind[ind["Indicateur"].str.startswith("dont fonctionnement")]
    bi = ind[ind["Indicateur"].str.startswith("dont investissement")]
    return {"sites": v("Sites solaires installés"), "kwc": v("Puissance installée", 1), "antennes": v("Antennes du réseau solaire"),
            "equipes": v("Équipes terrain constituées"), "pourvus": pourvus.strip(), "requis": requis.strip(),
            "manques": v("Postes manquants"),
            "budget": _fmt(bud["Valeur"].iloc[0]) if len(bud) else "⟨n.d.⟩",
            "budget_f": _fmt(bf["Valeur"].iloc[0]) if len(bf) else "⟨n.d.⟩",
            "budget_i": _fmt(bi["Valeur"].iloc[0]) if len(bi) else "⟨n.d.⟩"}


def remplir(texte: str, valeurs: dict) -> str:
    try:
        return texte.format(**valeurs)
    except (KeyError, IndexError, ValueError):
        return texte


def generer_pdf(langue: str, audience: str, titre: str, textes: dict, ind: pd.DataFrame, avert: list[str],
                genere_le: str, data=None) -> bytes:
    from .rapports import build_pdf_report, _fig_to_png_bytes
    import plotly.graph_objects as go
    from .ui import plotly_base_layout
    from .data import NAVY, GREEN, AMBER, RED
    en = langue == "EN"
    col_lib = "Indicator" if en else "Indicateur"
    valeurs = valeurs_gabarit(ind)
    kp = []
    for lib in ("Sites solaires installés", "Puissance installée", "Équipes terrain constituées", "Postes manquants"):
        r = ind[ind["Indicateur"] == lib]
        if len(r):
            u = r["Unité"].iloc[0]
            kp.append((r[col_lib].iloc[0], f"{_fmt(r['Valeur'].iloc[0])} {UNITES_EN.get(u, u) if en else u}"))
    b = ind[ind["Indicateur"].str.startswith("Budget prévisionnel")]
    if len(b):
        m = float(b["Valeur"].iloc[0]) / 1e6
        kp.append((b[col_lib].iloc[0], f"{m:,.1f} M {'XAF' if en else 'FCFA'}".replace(",", " ").replace(".", "." if en else ",")))
    sections = []
    for cle, tfr, ten in SECTIONS:
        sections.append({"titre": ten if en else tfr, "texte": remplir(textes[cle][1 if en else 0], valeurs),
                         "image_bytes": None, "tableau": None})
    if data is not None and getattr(data, "grid", None) is not None and not data.grid.empty and "Statut équipe" in data.grid.columns:
        cnt = data.grid["Statut équipe"].value_counts()
        lab = [{"Complète": "Complete", "Partielle": "Partial", "Critique": "Critical"}.get(x, x) if en else x for x in cnt.index]
        coul = {"Complète": GREEN, "Partielle": AMBER, "Critique": RED}
        fig = go.Figure(data=[go.Pie(labels=lab, values=cnt.values, hole=0.5,
                                     marker=dict(colors=[coul.get(x, NAVY) for x in cnt.index]))])
        sections.insert(2, {"titre": "Field team status" if en else "Statut des équipes terrain",
                            "texte": "Source: AER workbook, 'Données - Équipes' sheet." if en else "Source : classeur AER, feuille « Données - Équipes ».",
                            "image_bytes": _fig_to_png_bytes(plotly_base_layout(fig, height=320)), "tableau": None})
    bu = budget_registre()
    if bu is not None and not bu.empty:
        bb = bu.copy()
        bb["Montant prévu (FCFA)"] = pd.to_numeric(bb["Montant prévu (FCFA)"], errors="coerce").fillna(0)
        ex = sorted(bb["Exercice"].astype(str).unique())[-1]
        pa = bb[bb["Exercice"].astype(str) == ex].groupby("Activité")["Montant prévu (FCFA)"].sum().sort_values()
        fig = go.Figure(go.Bar(y=[a.split(":")[0].strip() for a in pa.index], x=pa.values / 1e6, orientation="h",
                               marker_color=NAVY))
        fig.update_layout(xaxis_title="Million XAF" if en else "Millions FCFA")
        t_act = pd.DataFrame({("Activity (official wording)" if en else "Activité"): list(pa.index[::-1]),
                              ("Million XAF" if en else "Millions FCFA"): [(f"{x / 1e6:,.1f}" if en else f"{x / 1e6:,.1f}".replace(",", " ").replace(".", ",")) for x in pa.values[::-1]]})
        sections.insert(len(sections) - 1, {"titre": (f"Planned budget {ex} by activity" if en else f"Budget prévisionnel {ex} par activité"),
                                            "texte": None,
                                            "image_bytes": _fig_to_png_bytes(plotly_base_layout(fig, height=360, legend=False),
                                                                             marge_gauche=110),
                                            "tableau": t_act})
    tab = ind[[col_lib, "Valeur", "Unité", "Source", "Date", "Statut"]].copy()
    tab["Valeur"] = tab["Valeur"].map(_fmt)
    if en:
        tab.columns = ["Indicator", "Value", "Unit", "Source", "Date", "Status"]
        tab["Unit"] = tab["Unit"].map(lambda u: UNITES_EN.get(u, u))
        tab["Status"] = tab["Status"].map({"Validé": "Validated", "Calculé": "Computed", "Provisoire": "Provisional",
                                           "À actualiser": "To be updated"}).fillna(tab["Status"])
    sections.append({"titre": "Annex — sourced indicators" if en else "Annexe — indicateurs sourcés",
                     "texte": ("Each figure is traceable to its source and date. Provisional figures come from registers "
                               "still being populated and must be confirmed before official use.") if en else
                              ("Chaque chiffre est rattaché à sa source et à sa date. Les chiffres provisoires proviennent "
                               "de registres en cours d'alimentation et doivent être confirmés avant tout usage officiel."),
                     "image_bytes": None, "tableau": tab})
    if avert:
        sections.append({"titre": "Data consistency points" if en else "Points de cohérence à lever",
                         "texte": "\n".join("- " + a for a in (controles(ind, en=True) if en else avert)),
                         "image_bytes": None, "tableau": None})
    sous = (f"Advocacy file — to the attention of: {AUDIENCES.get(audience, audience)}" if en
            else f"Dossier de plaidoyer — à l'attention de : {audience}")
    return build_pdf_report(titre, sous, genere_le, kp[:5], sections,
                            libelle_date="Generated on" if en else "Généré le")


def annexe_excel(ind: pd.DataFrame, avert: list[str]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        ind.to_excel(xw, sheet_name="Indicateurs - Indicators", index=False)
        pd.DataFrame({"Point de cohérence": avert or ["Aucun"]}).to_excel(xw, sheet_name="Cohérence", index=False)
    return buf.getvalue()
