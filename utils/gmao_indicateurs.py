"""Suivi de la maintenance des centrales — règles métier et indicateurs (fonctions pures, testées).

Aucun accès à la base ni à l'interface ici : les fonctions reçoivent des tableaux pandas et des paramètres,
et renvoient des valeurs. Les délais, poids et seuils viennent des paramètres de la page (jamais en dur dans
les calculs) ; les valeurs ci-dessous ne sont que les valeurs de départ.

Vocabulaire :
- « fiche » : un défaut des journaux de maintenance ou un bon d'intervention correctif saisi dans l'application ;
- « état détaillé » d'une centrale : 24 h/24, à vide, arrêt avant 18 h, arrêt après 18 h, à l'arrêt ;
- « en service H24 » = 24 h/24 + à vide ; « service partiel » = arrêt avant ou après 18 h.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from .gmao import cle

# ----------------------------------------------------------------------------- paramètres de départ
PRIORITES = ["URGENT", "CRITIQUE", "MAJEUR", "MINEUR", "Non renseignée"]
_PRIORITES = {"urgent": "URGENT", "urgente": "URGENT", "critical": "CRITIQUE", "critique": "CRITIQUE",
              "major": "MAJEUR", "majeur": "MAJEUR", "majeure": "MAJEUR", "minor": "MINEUR", "mineur": "MINEUR",
              "mineure": "MINEUR"}

# Délai de résolution en jours selon la priorité. None = « à compléter » : la fiche garde alors le nombre de
# jours prévu saisi dans le journal, s'il existe. URGENT : 2 j (affiché par le prototype) ; CRITIQUE : 7 j (déduit).
DELAIS_DEFAUT: dict[str, int | None] = {"URGENT": 2, "CRITIQUE": 7, "MAJEUR": None, "MINEUR": None}

POIDS_DEFAUT: dict = {
    "fiche": {"URGENT": 8, "CRITIQUE": 5, "MAJEUR": 2, "autre": 1}, "plafond_fiches": 20,
    "arret": 4, "plafond_arrets": 12,
    "sans_visite": 3, "sans_visite_mois": 6,
    "signaux": {"service_inf_95": 8, "batterie_vide_3j": 6, "ecart_cellules_100mv": 5, "rendement_stockage_inf_80": 3},
    "supervision": {"défaillante": 6, "déconnectée": 4},
    "seuil_tres_expose": 15, "fenetre_mois": 12,
}
LIBELLES_SIGNAUX = {"service_inf_95": "service inférieur à 95 %", "batterie_vide_3j": "batterie vide 3 jours ou plus",
                    "ecart_cellules_100mv": "écart entre cellules ≥ 100 mV",
                    "rendement_stockage_inf_80": "rendement du stockage inférieur à 80 %"}
SEUIL_RECIDIVE_DEFAUT = 5

H24, A_VIDE, AVANT_18H, APRES_18H, ARRET = ("Fonctionnement 24 h/24", "Fonctionne à vide", "Arrêt avant 18 h",
                                            "Arrêt après 18 h", "À l'arrêt")
PARTIEL_AUTRE, NON_MES, NON_RENSEIGNE = "Service partiel (horaire non précisé)", "Non mis en service", "Non renseigné"
ETATS_DETAILLES = [H24, A_VIDE, AVANT_18H, APRES_18H, PARTIEL_AUTRE, ARRET]
_ETATS = {"fonctionnementh24": H24, "fonctionnement24h24": H24, "enserviceh24": H24, "remiseenmarche": H24,
          "fonctionneavide": A_VIDE, "avide": A_VIDE, "fonctionnementavide": A_VIDE,
          "arretavant18h": AVANT_18H, "apres18h": APRES_18H, "arretapres18h": APRES_18H,
          "partielle": PARTIEL_AUTRE, "programme": PARTIEL_AUTRE, "servicepartiel": PARTIEL_AUTRE,
          "enarret": ARRET, "arretdemarche": ARRET, "alarret": ARRET,
          "nonmisenservice": NON_MES}
GROUPE = {H24: "En service H24", A_VIDE: "En service H24", AVANT_18H: "Service partiel", APRES_18H: "Service partiel",
          PARTIEL_AUTRE: "Service partiel", ARRET: "À l'arrêt", NON_MES: NON_MES, NON_RENSEIGNE: NON_RENSEIGNE}
GROUPES = ["En service H24", "Service partiel", "À l'arrêt", NON_MES, NON_RENSEIGNE]
TRANCHES_AGE = ["< 30 j", "30–90 j", "90–180 j", "180–365 j", "> 1 an"]


# ----------------------------------------------------------------------------- priorités et échéances
def priorite_normalisee(x) -> str:
    """Ramène les libellés des journaux (CRITICAL, MAJOR…) et du GMAO (Critique, Majeure…) à une seule liste."""
    if x is None or (not isinstance(x, str) and pd.isna(x)):
        return "Non renseignée"
    return _PRIORITES.get(cle(x), "Non renseignée")


def delai_resolution(priorite: str, delais: dict | None = None, jours_prevus=None) -> int | None:
    """Délai de résolution en jours : celui de la priorité s'il est paramétré, sinon le nombre de jours prévu
    saisi sur la fiche, sinon None (la fiche n'a alors pas d'échéance et ne peut pas être « hors délai »)."""
    d = (DELAIS_DEFAUT if delais is None else delais).get(priorite)
    if d is not None and not pd.isna(d):
        return int(d)
    if jours_prevus is not None and not pd.isna(jours_prevus) and jours_prevus >= 0:
        return int(jours_prevus)
    return None


def echeance(date_constat, priorite: str, delais: dict | None = None, jours_prevus=None) -> pd.Timestamp | None:
    d = delai_resolution(priorite, delais, jours_prevus)
    if d is None or date_constat is None or pd.isna(date_constat):
        return None
    return pd.Timestamp(date_constat).normalize() + pd.Timedelta(days=d)


def est_lineaire(materiel) -> bool:
    """Vrai pour un câble ou une ligne (quantités en mètres, non comparables à des pièces)."""
    k = cle(materiel)
    return k.startswith(("cable", "ligne")) or k.endswith(("cable", "cables"))


# ----------------------------------------------------------------------------- fiches (journaux + application)
COLONNES_FICHES = ["source", "ref", "cle_site", "site", "phase", "region", "date_constat", "date_cloture", "ouvert",
                   "priorite", "categorie", "materiel", "description", "qte_affectee", "qte_remplacee", "lineaire",
                   "site_arret_au_constat", "jours_prevus", "ligne"]


def fiches_depuis_journaux(d: pd.DataFrame | None) -> pd.DataFrame:
    """Défauts des journaux (sortie de gmao.normaliser_defauts) au format commun des fiches."""
    if d is None or d.empty:
        return pd.DataFrame(columns=COLONNES_FICHES)
    clos = d["resultat"] == "Clôturé"
    return pd.DataFrame({
        "source": d["source"], "ref": d["num"].map(lambda n: None if pd.isna(n) else f"n° {int(n)}"),
        "cle_site": d["cle_site"], "site": d["site"], "phase": d["phase"], "region": d["region"],
        "date_constat": pd.to_datetime(d["date_incident"], errors="coerce"),
        "date_cloture": pd.to_datetime(d["date_achevement"], errors="coerce").where(clos),
        "ouvert": ~clos, "priorite": d["priorite"].map(priorite_normalisee), "categorie": d["categorie"],
        "materiel": d["materiel"], "description": d["description"],
        "qte_affectee": pd.to_numeric(d["qte_affectee"], errors="coerce").fillna(0),
        "qte_remplacee": pd.to_numeric(d["qte_remplacee"], errors="coerce").fillna(0),
        "lineaire": d["lineaire"].astype(bool) if "lineaire" in d else False,
        "site_arret_au_constat": d["etat_arrivee"].astype(str).str.lower().str.contains("arr"),
        "jours_prevus": pd.to_numeric(d["jours_prevus"], errors="coerce"),
        "ligne": d.index})[COLONNES_FICHES].reset_index(drop=True)


def fiches_depuis_bi(bi: pd.DataFrame | None, statuts_ouverts: list[str]) -> pd.DataFrame:
    """Bons d'intervention correctifs de l'application au format commun (les BI annulés sont ignorés)."""
    if bi is None or bi.empty:
        return pd.DataFrame(columns=COLONNES_FICHES)
    b = bi[(bi["type"] == "Corrective") & (bi["statut"] != "Annulé")]
    if b.empty:
        return pd.DataFrame(columns=COLONNES_FICHES)
    ouvert = b["statut"].isin(statuts_ouverts)
    prevus = (pd.to_datetime(b["date_prevue"]) - pd.to_datetime(b["date_creation"])).dt.days
    q = lambda c: pd.to_numeric(b[c], errors="coerce").fillna(0) if c in b else 0  # noqa: E731
    return pd.DataFrame({
        "source": "Application", "ref": b["id"], "cle_site": b["site"].map(cle), "site": b["site"], "phase": b["phase"],
        "region": b["region"], "date_constat": pd.to_datetime(b["date_creation"], errors="coerce"),
        "date_cloture": pd.to_datetime(b["date_fin"], errors="coerce").where(~ouvert), "ouvert": ouvert,
        "priorite": b["priorite"].map(priorite_normalisee), "categorie": b["systeme"].fillna("Non renseignée"),
        "materiel": b["equipement"].fillna("Non renseigné"), "description": b["description"],
        "qte_affectee": q("qte_affectee"), "qte_remplacee": q("qte_remplacee"), "lineaire": False,
        "site_arret_au_constat": b["centrale_arret"].astype(bool), "jours_prevus": prevus,
        "ligne": None})[COLONNES_FICHES].reset_index(drop=True)


def completer_fiches(f: pd.DataFrame, aujourd_hui: pd.Timestamp, delais: dict | None = None) -> pd.DataFrame:
    """Ajoute échéance, retard, hors délai, âge (fiches ouvertes) et délai de résolution (fiches clôturées)."""
    f = f.copy()
    auj = pd.Timestamp(aujourd_hui).normalize()
    f["materiel"] = f["materiel"].map(lambda x: "Non renseigné" if x is None or pd.isna(x) or str(x).strip().lower() in ("", "nan", "none") else str(x).strip())
    # câbles et lignes : comptés en mètres dans les journaux, donc exclus des totaux en pièces
    f["lineaire"] = f["lineaire"].astype(bool) | f["materiel"].map(est_lineaire)
    f["echeance"] = [echeance(d, p, delais, j) for d, p, j in zip(f["date_constat"], f["priorite"], f["jours_prevus"])]
    f["echeance"] = pd.to_datetime(f["echeance"])
    f["ouvert"] = f["ouvert"].astype(bool)
    f["age_j"] = (auj - f["date_constat"].dt.normalize()).dt.days.where(f["ouvert"])
    retard = (auj - f["echeance"]).dt.days
    f["hors_delai"] = f["ouvert"] & f["echeance"].notna() & (retard > 0)
    f["retard_j"] = retard.where(f["hors_delai"])
    f["delai_j"] = (f["date_cloture"].dt.normalize() - f["date_constat"].dt.normalize()).dt.days.where(~f["ouvert"])
    f["mois"] = f["date_constat"].dt.to_period("M").dt.to_timestamp()
    return f


def filtrer_fiches(f: pd.DataFrame, sources=None, regions=None, phases=None, categories=None, priorites=None,
                   statut: str | None = None, sites: set | None = None, debut=None, fin=None) -> tuple[pd.DataFrame, int]:
    """Applique les filtres globaux. Renvoie aussi le nombre de fiches SANS DATE écartées par le filtre de
    période : elles ne peuvent pas être situées dans le temps, mais elles sont comptées et annoncées."""
    v = f
    for col, val in (("source", sources), ("region", regions), ("phase", phases), ("categorie", categories),
                     ("priorite", priorites)):
        if val:
            v = v[v[col].isin(val)]
    if statut == "Ouvert":
        v = v[v["ouvert"]]
    elif statut == "Clôturé":
        v = v[~v["ouvert"]]
    if sites is not None:
        v = v[v["cle_site"].isin(sites)]
    sans_date = 0
    if debut is not None or fin is not None:
        sans_date = int(v["date_constat"].isna().sum())
        d0 = pd.Timestamp(debut) if debut is not None else pd.Timestamp.min
        d1 = (pd.Timestamp(fin) + pd.Timedelta(days=1)) if fin is not None else pd.Timestamp.max
        v = v[(v["date_constat"] >= d0) & (v["date_constat"] < d1)]
    return v, sans_date


# ----------------------------------------------------------------------------- indicateurs de maintenance
def mttr_median(f: pd.DataFrame) -> dict:
    """MTTR médian (constat → clôture, en jours) sur les seules fiches clôturées aux dates exploitables.

    Les clôtures enregistrées le jour même du constat sont écartées du calcul et comptées à part : dans les
    journaux, elles viennent le plus souvent d'une date de clôture recopiée, et elles ramenaient la médiane à 0."""
    clos = f[~f["ouvert"]]
    d = clos["delai_j"]
    sans_date = int(d.isna().sum())
    incoherent = int((d < 0).sum())
    meme_jour = int((d == 0).sum())
    retenus = d[d > 0]
    return {"mttr": float(retenus.median()) if len(retenus) else None, "retenues": int(len(retenus)),
            "meme_jour": meme_jour, "sans_date": sans_date, "incoherentes": incoherent, "cloturees": int(len(clos)),
            "mttr_avec_meme_jour": float(d[d >= 0].median()) if (d >= 0).any() else None}


def indicateurs_maintenance(f: pd.DataFrame, seuil_recidive: int = SEUIL_RECIDIVE_DEFAUT) -> dict:
    """Indicateurs du bloc « Maintenance » sur les fiches fournies (déjà filtrées et complétées)."""
    n = len(f)
    ouv, clos = f[f["ouvert"]], f[~f["ouvert"]]
    dates_ok = clos[clos["date_cloture"].notna() & clos["echeance"].notna()]
    par_site = f.groupby("cle_site").size() if n else pd.Series(dtype=int)
    batt = f[f["materiel"].map(cle).isin({"batterie", "batteries"})]
    aff, remp = float(batt["qte_affectee"].sum()), float(batt["qte_remplacee"].sum())
    return {
        "enregistrees": n, "sites_touches": int(f["cle_site"].nunique()) if n else 0,
        "backlog": int(len(ouv)), "age_median_j": float(ouv["age_j"].median()) if ouv["age_j"].notna().any() else None,
        "hors_delai": int(ouv["hors_delai"].sum()),
        "pct_hors_delai": 100 * ouv["hors_delai"].sum() / len(ouv) if len(ouv) else None,
        "ouvertes_sans_echeance": int(ouv["echeance"].isna().sum()),
        "urgents_critiques_ouverts": int(ouv["priorite"].isin(["URGENT", "CRITIQUE"]).sum()),
        "urgents_critiques_hors_delai": int((ouv["priorite"].isin(["URGENT", "CRITIQUE"]) & ouv["hors_delai"]).sum()),
        "cloturees": int(len(clos)), "taux_cloture": 100 * len(clos) / n if n else None,
        "respect_delai": 100 * (dates_ok["date_cloture"].dt.normalize() <= dates_ok["echeance"]).mean() if len(dates_ok) else None,
        "respect_delai_base": int(len(dates_ok)),
        "mttr": mttr_median(f),
        "recidivistes": int((par_site >= seuil_recidive).sum()),
        "constats_arret": int(f["site_arret_au_constat"].sum()) if n else 0,
        "pct_constats_arret": 100 * f["site_arret_au_constat"].mean() if n else None,
        "batteries_affectees": aff, "batteries_remplacees": remp,
        "pct_batteries": 100 * remp / aff if aff else None,
        "sans_date_constat": int(f["date_constat"].isna().sum()),
        "materiel_non_renseigne": int((f["materiel"] == "Non renseigné").sum()),
    }


# ----------------------------------------------------------------------------- états des centrales
def etat_detaille(etat, detail=None) -> str:
    """État détaillé d'une centrale à partir du libellé d'état (journal ou saisie) et d'un détail éventuel
    (« Fonctionne à vide »). Un libellé inconnu donne « Non renseigné » : rien n'est deviné."""
    for x in (detail, etat):
        if x is not None and not (not isinstance(x, str) and pd.isna(x)):
            e = _ETATS.get(cle(x))
            if e:
                return e
    return NON_RENSEIGNE


def tableau_etats(sites: pd.DataFrame, phases=("Phase 1", "Phase 2")) -> pd.DataFrame:
    """Nombre, part (%) et puissance (kWc) des centrales par phase et par état détaillé. Les sites non mis en
    service (Phase 3) ne sont pas comptés. Une ligne par (phase, état) + les totaux."""
    s = sites[sites["phase"].isin(phases) & (sites["etat"] != NON_MES)]
    lignes = []
    for ph, g in list(s.groupby("phase")) + [("Total", s)]:
        for e in ETATS_DETAILLES + [NON_RENSEIGNE]:
            x = g[g["etat"] == e]
            lignes.append({"phase": ph, "etat": e, "sites_phase": len(g), "nb": len(x),
                           "pct": 100 * len(x) / len(g) if len(g) else 0.0, "kwc": float(x["kwc"].sum())})
    return pd.DataFrame(lignes)


def puissance_parc(sites: pd.DataFrame, cible_kwc: float | None = None) -> dict:
    """Puissance installée, en service (H24 + partiel), partielle, à l'arrêt et non mise en service, par phase."""
    gr = sites["etat"].map(GROUPE)
    kw = lambda m: float(sites.loc[m, "kwc"].sum())  # noqa: E731
    lignes = []
    for ph, g in list(sites.groupby("phase")) + [("Total", sites)]:
        gg = g["etat"].map(GROUPE)
        k = lambda m: float(g.loc[m, "kwc"].sum())  # noqa: E731
        inst, serv = float(g["kwc"].sum()), k(gg.isin(["En service H24", "Service partiel"]))
        mes = inst - k(gg == NON_MES)
        lignes.append({"Phase": ph, "Sites": len(g), "Installée (kWc)": inst, "En service (kWc)": serv,
                       "dont partiel (kWc)": k(gg == "Service partiel"), "À l'arrêt (kWc)": k(gg == "À l'arrêt"),
                       "Non mise en service (kWc)": k(gg == NON_MES), "Non renseignée (kWc)": k(gg == NON_RENSEIGNE),
                       "% exploité": 100 * serv / mes if mes else None})
    installee = float(sites["kwc"].sum())
    en_service = kw(gr.isin(["En service H24", "Service partiel"]))
    cible = installee if cible_kwc in (None, 0) or pd.isna(cible_kwc) else float(cible_kwc)
    return {"cible": cible, "installee": installee, "en_service": en_service, "partiel": kw(gr == "Service partiel"),
            "arret": kw(gr == "À l'arrêt"), "sites_arret": int((gr == "À l'arrêt").sum()),
            "non_mes": kw(gr == NON_MES), "sites_non_mes": int((gr == NON_MES).sum()),
            "pct_cible": 100 * en_service / cible if cible else None, "ecart_cible": cible - en_service,
            "par_phase": pd.DataFrame(lignes)}


# ----------------------------------------------------------------------------- score d'exposition à l'arrêt
def score_exposition(fiches_recentes: dict[str, int], arrets_recents: int, jours_depuis_visite: float | None,
                     signaux: dict[str, bool] | None = None, supervision: str | None = None,
                     poids: dict | None = None) -> tuple[int, list[str]]:
    """Score d'exposition d'un site en service à un arrêt : une AIDE AU TRI, pas une mesure.

    fiches_recentes : nombre de fiches ouvertes récentes par priorité ; arrets_recents : arrêts sur la fenêtre ;
    jours_depuis_visite : None si le site n'a jamais été visité ; signaux : signaux de performance constatés ;
    supervision : « défaillante », « déconnectée » ou None. Renvoie (points, motifs)."""
    p = POIDS_DEFAUT if poids is None else poids
    pts, motifs = 0, []
    pf = p["fiche"]
    brut = sum(n * pf.get(prio, pf["autre"]) for prio, n in fiches_recentes.items() if n)
    nb = sum(n for n in fiches_recentes.values() if n)
    if nb:
        s = min(brut, p["plafond_fiches"])
        pts += s
        uc = fiches_recentes.get("URGENT", 0) + fiches_recentes.get("CRITIQUE", 0)
        motifs.append(f"{nb} fiche(s) récente(s)" + (f" dont {uc} urg./crit." if uc else "") + f" : {s} pt")
    if arrets_recents:
        s = min(arrets_recents * p["arret"], p["plafond_arrets"])
        pts += s
        motifs.append(f"{arrets_recents} arrêt(s) en {p['fenetre_mois']} mois : {s} pt")
    limite = p["sans_visite_mois"] * 30.44
    if jours_depuis_visite is None or pd.isna(jours_depuis_visite) or jours_depuis_visite > limite:
        pts += p["sans_visite"]
        motifs.append(("jamais visité" if jours_depuis_visite is None or pd.isna(jours_depuis_visite)
                       else f"sans visite depuis {int(jours_depuis_visite)} j") + f" : {p['sans_visite']} pt")
    for k, actif in (signaux or {}).items():
        if actif and k in p["signaux"]:
            pts += p["signaux"][k]
            motifs.append(f"{LIBELLES_SIGNAUX.get(k, k)} : {p['signaux'][k]} pt")
    if supervision in p["supervision"]:
        pts += p["supervision"][supervision]
        motifs.append(f"supervision {supervision} : {p['supervision'][supervision]} pt")
    return int(pts), motifs


def scores_sites(sites: pd.DataFrame, f: pd.DataFrame, arrets: pd.DataFrame, visites: pd.DataFrame,
                 aujourd_hui: pd.Timestamp, poids: dict | None = None, supervision: dict[str, str] | None = None,
                 signaux: dict[str, dict] | None = None) -> pd.DataFrame:
    """Score de chaque site en service H24. `arrets` et `visites` : colonnes cle_site et date."""
    p = POIDS_DEFAUT if poids is None else poids
    auj = pd.Timestamp(aujourd_hui).normalize()
    debut = auj - pd.DateOffset(months=int(p["fenetre_mois"]))
    rec = f[f["ouvert"] & (f["date_constat"] >= debut)]
    par_prio = rec.groupby(["cle_site", "priorite"]).size().unstack(fill_value=0) if len(rec) else pd.DataFrame()
    anciennes = f[f["ouvert"] & ~(f["date_constat"] >= debut)].groupby("cle_site").size() if len(f) else pd.Series(dtype=int)
    a = arrets[arrets["date"] >= debut].groupby("cle_site").size() if arrets is not None and len(arrets) else pd.Series(dtype=int)
    v = visites.dropna(subset=["date"]).groupby("cle_site")["date"].max() if visites is not None and len(visites) else pd.Series(dtype="datetime64[ns]")
    lignes = []
    for s in sites[sites["etat"].map(GROUPE) == "En service H24"].itertuples():
        fr = par_prio.loc[s.cle_site].to_dict() if len(par_prio) and s.cle_site in par_prio.index else {}
        der = v.get(s.cle_site)
        jours = None if der is None or pd.isna(der) else (auj - pd.Timestamp(der).normalize()).days
        pts, motifs = score_exposition(fr, int(a.get(s.cle_site, 0)), jours, (signaux or {}).get(s.cle_site),
                                       (supervision or {}).get(s.cle_site), p)
        anc = int(anciennes.get(s.cle_site, 0))
        if anc:
            motifs.append(f"+ {anc} fiche(s) ancienne(s), non comptée(s)")
        lignes.append({"cle_site": s.cle_site, "Site": s.site, "Phase": s.phase, "Région": s.region, "kWc": s.kwc,
                       "Points": pts, "Motifs": " · ".join(motifs), "Zone": getattr(s, "zone", None),
                       "Responsable": getattr(s, "responsable", None),
                       "Dernière visite": None if der is None or pd.isna(der) else pd.Timestamp(der)})
    out = pd.DataFrame(lignes)
    return out.sort_values(["Points", "kWc"], ascending=False).reset_index(drop=True) if len(out) else out


# ----------------------------------------------------------------------------- priorités d'intervention
def a_remettre_en_service(sites: pd.DataFrame, f: pd.DataFrame) -> pd.DataFrame:
    """Sites à l'arrêt ou en service partiel, avec le suivi : fiches ouvertes, âge de la plus ancienne, « sans fiche »."""
    s = sites[sites["etat"].map(GROUPE).isin(["À l'arrêt", "Service partiel"])]
    ouv = f[f["ouvert"]]
    nb = ouv.groupby("cle_site").size()
    age = ouv.groupby("cle_site")["age_j"].max()
    out = pd.DataFrame({"cle_site": s["cle_site"], "Site": s["site"], "Phase": s["phase"], "Région": s["region"],
                        "kWc": s["kwc"], "État": s["etat"], "Cause déclarée": s["cause"],
                        "Fiches ouvertes": s["cle_site"].map(nb).fillna(0).astype(int).values,
                        "Âge de la plus ancienne (j)": s["cle_site"].map(age).values})
    out["Suivi"] = [("sans fiche" if n == 0 else f"{n} fiche(s)" + ("" if pd.isna(a) else f" · {int(a)} j"))
                    for n, a in zip(out["Fiches ouvertes"], out["Âge de la plus ancienne (j)"])]
    ordre = out["État"].map({ARRET: 0}).fillna(1)
    return out.assign(_o=ordre).sort_values(["_o", "kWc"], ascending=[True, False]).drop(columns="_o").reset_index(drop=True)


def priorites_intervention(sites: pd.DataFrame, f: pd.DataFrame, scores: pd.DataFrame, visites: pd.DataFrame,
                           aujourd_hui: pd.Timestamp, poids: dict | None = None) -> dict:
    p = POIDS_DEFAUT if poids is None else poids
    auj = pd.Timestamp(aujourd_hui).normalize()
    gr = sites["etat"].map(GROUPE)
    rem = a_remettre_en_service(sites, f)
    en_service = sites[gr.isin(["En service H24", "Service partiel"])]
    der = visites.dropna(subset=["date"]).groupby("cle_site")["date"].max() if visites is not None and len(visites) else pd.Series(dtype="datetime64[ns]")
    d = en_service["cle_site"].map(der)
    limite = auj - pd.Timedelta(days=p["sans_visite_mois"] * 30.44)
    ouv = f[f["ouvert"]]
    return {
        "tres_exposes": int((scores["Points"] >= p["seuil_tres_expose"]).sum()) if len(scores) else 0,
        "en_service_h24": int((gr == "En service H24").sum()),
        "a_remettre": len(rem), "a_remettre_sans_fiche": int((rem["Fiches ouvertes"] == 0).sum()) if len(rem) else 0,
        "phase1_arret": int(((gr == "À l'arrêt") & (sites["phase"] == "Phase 1")).sum()),
        "en_service": len(en_service),
        "sans_visite": int((d.isna() | (d < limite)).sum()), "jamais_visites": int(d.isna().sum()),
        "urgents_critiques_hors_delai": int((ouv["priorite"].isin(["URGENT", "CRITIQUE"]) & ouv["hors_delai"]).sum()),
    }


def interruptions_non_signalees(sites: pd.DataFrame, f: pd.DataFrame, aujourd_hui: pd.Timestamp, jours: int = 90,
                                deconnectees: dict[str, pd.Timestamp] | None = None) -> pd.DataFrame:
    """Sites déclarés EN SERVICE pour lesquels un indice contredit l'état saisi : une fiche encore ouverte a
    constaté le site à l'arrêt il y a moins de `jours` jours, ou la supervision ne reçoit plus de données.
    Ce sont des points À VÉRIFIER (interruption peut-être non signalée), pas des arrêts constatés."""
    auj = pd.Timestamp(aujourd_hui).normalize()
    s = sites[sites["etat"].map(GROUPE).isin(["En service H24", "Service partiel"])].set_index("cle_site")
    lignes = []
    x = f[f["ouvert"] & f["site_arret_au_constat"] & (f["date_constat"] >= auj - pd.Timedelta(days=jours))]
    for k, g in x.groupby("cle_site"):
        if k in s.index:
            d = g["date_constat"].max()
            lignes.append({"cle_site": k, "Indice": f"{len(g)} fiche(s) ouverte(s) constatant le site à l'arrêt, "
                                                    f"la dernière le {d:%d/%m/%Y}", "Date de l'indice": d})
    for k, d in (deconnectees or {}).items():
        if k in s.index:
            lignes.append({"cle_site": k, "Indice": f"Supervision sans donnée depuis le {pd.Timestamp(d):%d/%m/%Y}",
                           "Date de l'indice": pd.Timestamp(d)})
    out = pd.DataFrame(lignes, columns=["cle_site", "Indice", "Date de l'indice"])
    if out.empty:
        return out.assign(Site=None, Région=None, **{"État déclaré": None})
    out["Site"], out["Région"], out["État déclaré"] = (out["cle_site"].map(s[c]) for c in ("site", "region", "etat"))
    return out.sort_values("Date de l'indice", ascending=False).reset_index(drop=True)


# ----------------------------------------------------------------------------- séries pour les graphiques
def defauts_par_mois(f: pd.DataFrame) -> pd.DataFrame:
    d = f.dropna(subset=["mois"])
    t = d.groupby(["mois", d["ouvert"].map({True: "Ouverts", False: "Clôturés"})]).size().unstack(fill_value=0)
    return t.reindex(columns=["Clôturés", "Ouverts"], fill_value=0).reset_index().rename(columns={"mois": "Mois"})


def backlog_par_anciennete(f: pd.DataFrame) -> pd.DataFrame:
    """Fiches ouvertes par tranche d'âge, dans le délai (ou sans échéance) / hors délai."""
    o = f[f["ouvert"] & f["age_j"].notna()]
    tr = pd.cut(o["age_j"], [-10**6, 29, 90, 180, 365, 10**6], labels=TRANCHES_AGE)
    t = pd.crosstab(tr, o["hors_delai"].map({True: "Hors délai", False: "Dans le délai"}), dropna=False)
    return t.reindex(index=TRANCHES_AGE, columns=["Dans le délai", "Hors délai"], fill_value=0).reset_index(names="Âge")


def repartition(f: pd.DataFrame, colonne: str, libelle: str) -> pd.DataFrame:
    """Fiches par valeur d'une colonne : total, ouvertes, clôturées, ouvertes hors délai."""
    g = f.assign(_c=f[colonne].fillna("Non renseigné")).groupby("_c")
    t = pd.DataFrame({"Défauts": g.size(), "Ouverts": g["ouvert"].sum().astype(int),
                      "Hors délai": g["hors_delai"].sum().astype(int)})
    t["Clôturés"] = t["Défauts"] - t["Ouverts"]
    return t.sort_values("Défauts", ascending=False).reset_index().rename(columns={"_c": libelle})


def top_sites(f: pd.DataFrame, sites: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    g = f.groupby("cle_site")
    t = pd.DataFrame({"Site": g["site"].first(), "Région": g["region"].first(), "Défauts": g.size(),
                      "Ouverts": g["ouvert"].sum().astype(int)})
    etats = sites.drop_duplicates("cle_site").set_index("cle_site")["etat"]
    t["État"] = t.index.map(etats).fillna(NON_RENSEIGNE)
    return t.sort_values(["Défauts", "Ouverts"], ascending=False).head(n).reset_index(drop=True)[
        ["Site", "Région", "État", "Défauts", "Ouverts"]]


def materiel_affecte_remplace(f: pd.DataFrame) -> pd.DataFrame:
    """Matériel affecté, remplacé et reste à fournir, en pièces. Les câbles et lignes (mètres) sont exclus.
    Les fiches au matériel non renseigné sont regroupées sous « Non renseigné » pour rester visibles."""
    p = f[~f["lineaire"].astype(bool)]
    t = p.groupby("materiel").agg(Affecté=("qte_affectee", "sum"), Remplacé=("qte_remplacee", "sum"),
                                  Fiches=("materiel", "size")).reset_index().rename(columns={"materiel": "Matériel"})
    t["Reste à fournir"] = (t["Affecté"] - t["Remplacé"]).clip(lower=0)
    return t[t["Affecté"] > 0].sort_values("Reste à fournir", ascending=False).reset_index(drop=True)


def etat_par_region(sites: pd.DataFrame) -> pd.DataFrame:
    t = pd.crosstab(sites["region"].fillna("Non renseignée"), sites["etat"].map(GROUPE))
    return t.reindex(columns=[c for c in GROUPES if c in t.columns]).reset_index(names="Région")


# ============================================================================= lot 2 : parc, backlog, fiche
PRIORITE_VERS_BI = {"URGENT": "Urgente", "CRITIQUE": "Critique", "MAJEUR": "Majeure", "MINEUR": "Mineure"}
ETATS_SAISIE = [H24, A_VIDE, AVANT_18H, APRES_18H, ARRET, NON_MES]
ETATS_ARRIVEE = ["En marche", "Service partiel", "À l'arrêt"]
FILTRES_DELAI = ["Tous", "Hors délai", "Dans le délai", "Sans échéance"]
# Causes d'arrêt relevées sur le prototype (liste de départ, modifiable dans les paramètres)
CAUSES_ARRET_DEFAUT = ["Batteries défectueuses", "Panne équipement", "Défaut réseau", "Réseau de distribution non disponible",
                       "Vandalisme", "Météo", "Brûlé", "Autre", "Non précisée"]
COLONNES_ETATS_SAISIS = ["horodatage", "cle_site", "site", "etat", "cause", "date_effet", "commentaire", "auteur"]
_VIDES = {"", "nan", "none", "null", "non renseigné", "non renseigne", "-", "—"}


def est_vide(x) -> bool:
    """Vrai pour une valeur absente ou un texte qui ne dit rien (« nan », « — », espaces…)."""
    return x is None or (not isinstance(x, str) and pd.isna(x)) or (isinstance(x, str) and x.strip().lower() in _VIDES)


def controler_fiche(v: dict, aujourd_hui: pd.Timestamp) -> list[str]:
    """Anomalies bloquantes d'une fiche de défaut avant enregistrement (liste vide = fiche valide).
    Champs attendus : site, date_constat, priorite, categorie, materiel, description, qte_affectee,
    qte_remplacee, cloturee, date_cloture."""
    err = []
    auj = pd.Timestamp(aujourd_hui).normalize()
    for champ, lib in (("site", "le site"), ("categorie", "la catégorie"), ("materiel", "le matériel affecté"),
                       ("description", "la description du problème")):
        if est_vide(v.get(champ)):
            err.append(f"Renseigne {lib}.")
    if v.get("priorite") not in PRIORITE_VERS_BI:
        err.append("Choisis une priorité : URGENT, CRITIQUE, MAJEUR ou MINEUR.")
    d = v.get("date_constat")
    if d is None or pd.isna(d):
        err.append("Renseigne la date de constat.")
    elif pd.Timestamp(d).normalize() > auj:
        err.append("La date de constat ne peut pas être dans le futur.")
    qa, qr = v.get("qte_affectee") or 0, v.get("qte_remplacee") or 0
    if qa < 0 or qr < 0:
        err.append("Les quantités ne peuvent pas être négatives.")
    elif qr > qa:
        err.append("La quantité remplacée dépasse la quantité affectée.")
    if v.get("cloturee"):
        c = v.get("date_cloture")
        if c is None or pd.isna(c):
            err.append("Une fiche clôturée doit avoir une date de clôture.")
        elif d is not None and not pd.isna(d) and pd.Timestamp(c).normalize() < pd.Timestamp(d).normalize():
            err.append("La date de clôture précède la date de constat.")
        elif pd.Timestamp(c).normalize() > auj:
            err.append("La date de clôture ne peut pas être dans le futur.")
    return err


def controler_etat(site, etat, date_effet, aujourd_hui: pd.Timestamp, cause=None) -> list[str]:
    err = []
    if est_vide(site):
        err.append("Choisis une centrale.")
    if etat not in ETATS_SAISIE:
        err.append("Choisis un état dans la liste.")
    if date_effet is None or pd.isna(date_effet):
        err.append("Renseigne la date à laquelle l'état a été constaté.")
    elif pd.Timestamp(date_effet).normalize() > pd.Timestamp(aujourd_hui).normalize():
        err.append("La date de constat de l'état ne peut pas être dans le futur.")
    if GROUPE.get(etat) in ("À l'arrêt", "Service partiel") and est_vide(cause):
        err.append("Indique la cause (ou « Non précisée ») pour un site à l'arrêt ou en service partiel.")
    return err


def appliquer_etats_saisis(sites: pd.DataFrame, saisies: pd.DataFrame | None) -> pd.DataFrame:
    """Remplace l'état issu des journaux par le dernier état SAISI dans l'application, quand il existe (date
    d'effet la plus récente, puis saisie la plus récente). Ajoute « etat_date » et « etat_source »."""
    s = sites.copy()
    s["etat_date"], s["etat_source"] = pd.NaT, "Journal"
    s.loc[s["etat"] == NON_MES, "etat_source"] = "Référentiel"
    if saisies is None or saisies.empty:
        return s
    d = saisies.assign(date_effet=pd.to_datetime(saisies["date_effet"]), horodatage=pd.to_datetime(saisies["horodatage"]))
    d = d.sort_values(["date_effet", "horodatage"]).drop_duplicates("cle_site", keep="last").set_index("cle_site")
    m = s["cle_site"].isin(d.index)
    for col, src in (("etat", "etat"), ("cause", "cause"), ("etat_date", "date_effet")):
        s.loc[m, col] = s.loc[m, "cle_site"].map(d[src]).values
    s.loc[m, "etat_source"] = "Saisie"
    s["etat_date"] = pd.to_datetime(s["etat_date"])
    return s


def backlog(f: pd.DataFrame, recherche: str = "", regions=None, zones=None, priorites=None, categories=None,
            delai: str = "Tous", zone_par_site: dict | None = None) -> pd.DataFrame:
    """Fiches ouvertes, filtrées, triées par priorité (URGENT d'abord) puis de la plus en retard à la plus récente."""
    b = f[f["ouvert"]].copy()
    b["zone"] = b["cle_site"].map(zone_par_site or {})
    for col, val in (("region", regions), ("zone", zones), ("priorite", priorites), ("categorie", categories)):
        if val:
            b = b[b[col].isin(val)]
    if delai == "Hors délai":
        b = b[b["hors_delai"]]
    elif delai == "Dans le délai":
        b = b[~b["hors_delai"] & b["echeance"].notna()]
    elif delai == "Sans échéance":
        b = b[b["echeance"].isna()]
    q = (recherche or "").strip()
    if q:
        texte = b[["site", "description", "materiel", "ref"]].apply(lambda col: col.map(lambda x: "" if est_vide(x) else str(x)))
        texte = texte["site"] + " " + texte["description"] + " " + texte["materiel"] + " " + texte["ref"]
        b = b[texte.str.contains(q, case=False, regex=False)]
    b["_p"] = b["priorite"].map({p: i for i, p in enumerate(PRIORITES)})
    return b.sort_values(["_p", "date_constat"], na_position="last").drop(columns="_p").reset_index(drop=True)


def synthese_par_region(sites: pd.DataFrame, f: pd.DataFrame) -> pd.DataFrame:
    """Par région : sites, puissance installée et en service, % exploité (sur la puissance mise en service),
    sites à l'arrêt, défauts ouverts."""
    gr = sites["etat"].map(GROUPE)
    ouv = f[f["ouvert"]].groupby("cle_site").size()
    x = sites.assign(_serv=sites["kwc"].where(gr.isin(["En service H24", "Service partiel"]), 0.0),
                     _mes=sites["kwc"].where(gr != NON_MES, 0.0), _arr=(gr == "À l'arrêt").astype(int),
                     _ouv=sites["cle_site"].map(ouv).fillna(0), region=sites["region"].fillna("Non renseignée"))
    t = x.groupby("region").agg(Sites=("cle_site", "size"), **{"Installée (kWc)": ("kwc", "sum"), "En service (kWc)": ("_serv", "sum")},
                                _mes=("_mes", "sum"), **{"À l'arrêt": ("_arr", "sum"), "Défauts ouverts": ("_ouv", "sum")})
    t["% exploité"] = (100 * t["En service (kWc)"] / t["_mes"]).where(t["_mes"] > 0)
    t["Défauts ouverts"] = t["Défauts ouverts"].astype(int)
    return t.drop(columns="_mes").reset_index().rename(columns={"region": "Région"})[
        ["Région", "Sites", "Installée (kWc)", "En service (kWc)", "% exploité", "À l'arrêt", "Défauts ouverts"]]


def table_sites(sites: pd.DataFrame, f: pd.DataFrame, arrets: pd.DataFrame, visites: pd.DataFrame, annee: int) -> pd.DataFrame:
    """Une ligne par centrale : état, cause, défauts ouverts et hors délai, arrêts de l'année, dernière visite,
    dernier défaut."""
    ouv = f[f["ouvert"]]
    par = lambda serie: sites["cle_site"].map(serie)  # noqa: E731
    a = arrets[arrets["date"].dt.year == annee].groupby("cle_site").size() if arrets is not None and len(arrets) else pd.Series(dtype=int)
    v = visites.groupby("cle_site")["date"].max() if visites is not None and len(visites) else pd.Series(dtype="datetime64[ns]")
    out = pd.DataFrame({
        "cle_site": sites["cle_site"], "Site": sites["site"], "Région": sites["region"], "Zone": sites["zone"],
        "kWc": sites["kwc"], "Phase": sites["phase"], "Responsable": sites["responsable"], "État": sites["etat"],
        "Cause / observation": sites["cause"],
        "Ouverts": par(ouv.groupby("cle_site").size()).fillna(0).astype(int),
        "Hors délai": par(ouv[ouv["hors_delai"]].groupby("cle_site").size()).fillna(0).astype(int),
        f"Arrêts {annee}": par(a).fillna(0).astype(int),
        "Dernière visite": pd.to_datetime(par(v)), "Dernier défaut": pd.to_datetime(par(f.groupby("cle_site")["date_constat"].max()))})
    for c in ("etat_date", "etat_source"):
        if c in sites:
            out[{"etat_date": "État constaté le", "etat_source": "Source de l'état"}[c]] = sites[c].values
    return out.reset_index(drop=True)


# ============================================================================= lot 3 : arrêts et disponibilité
COLONNES_ARRETS = ["id", "cle_site", "site", "debut", "fin", "cause", "commentaire", "equipe", "source",
                   "date_a_verifier", "auteur", "horodatage", "remise_par"]
MOIS_COURTS = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
AVERTISSEMENT_DISPONIBILITE = ("Le calcul n'est fiable que si chaque arrêt et chaque remise en marche sont saisis.")


def controler_arret(site, debut, cause, maintenant: pd.Timestamp, sites_deja_a_l_arret: set | None = None) -> list[str]:
    """Anomalies bloquantes d'une déclaration d'arrêt."""
    err = []
    if est_vide(site):
        err.append("Choisis la centrale à l'arrêt.")
    elif sites_deja_a_l_arret and cle(site) in sites_deja_a_l_arret:
        err.append("Un arrêt est déjà en cours pour cette centrale : enregistre d'abord sa remise en marche.")
    if debut is None or pd.isna(debut):
        err.append("Renseigne la date et l'heure du début de l'arrêt.")
    elif pd.Timestamp(debut) > pd.Timestamp(maintenant):
        err.append("Le début de l'arrêt ne peut pas être dans le futur.")
    if est_vide(cause):
        err.append("Indique la cause de l'arrêt (ou « Non précisée »).")
    return err


def controler_remise(debut, fin, maintenant: pd.Timestamp) -> list[str]:
    """Anomalies bloquantes d'une remise en marche."""
    if fin is None or pd.isna(fin):
        return ["Renseigne la date et l'heure de la remise en marche."]
    err = []
    if pd.Timestamp(fin) > pd.Timestamp(maintenant):
        err.append("La remise en marche ne peut pas être dans le futur.")
    if debut is not None and not pd.isna(debut) and pd.Timestamp(fin) < pd.Timestamp(debut):
        err.append("La remise en marche précède le début de l'arrêt.")
    return err


def heures_indisponibles(intervalles: list[tuple], debut: pd.Timestamp, fin: pd.Timestamp) -> float:
    """Heures d'arrêt d'UN site dans la période [debut, fin] : union des intervalles (deux arrêts qui se
    chevauchent ne sont pas comptés deux fois). Une fin absente = arrêt encore en cours ; un début absent
    (date inconnue) = arrêt antérieur à la période."""
    bornes = []
    for d, f_ in intervalles:
        d = debut if d is None or pd.isna(d) else max(pd.Timestamp(d), debut)
        f_ = fin if f_ is None or pd.isna(f_) else min(pd.Timestamp(f_), fin)
        if f_ > d:
            bornes.append((d, f_))
    total, courant = 0.0, None
    for d, f_ in sorted(bornes):
        if courant is None or d > courant[1]:
            if courant is not None:
                total += (courant[1] - courant[0]).total_seconds()
            courant = [d, f_]
        else:
            courant[1] = max(courant[1], f_)
    if courant is not None:
        total += (courant[1] - courant[0]).total_seconds()
    return total / 3600


def disponibilite_parc(episodes: pd.DataFrame, perimetre: set, a_l_arret_sans_episode: set, debut: pd.Timestamp,
                       fin: pd.Timestamp, compter_dates_a_verifier: bool = False) -> dict:
    """Disponibilité du parc = 1 − (durée cumulée des arrêts ÷ (sites du périmètre × durée de la période)).

    - `perimetre` : centrales mises en service ; `a_l_arret_sans_episode` : centrales déclarées à l'arrêt sans
      arrêt en cours saisi — elles sont comptées indisponibles sur TOUTE la période.
    - Un arrêt CLOS dont la date de début est « à vérifier » est écarté du calcul (et compté à part), sauf si
      `compter_dates_a_verifier`. Un arrêt EN COURS à la date à vérifier est compté sur toute la période, comme
      un site à l'arrêt sans arrêt saisi : seul son début est incertain, pas l'arrêt."""
    duree_h = (pd.Timestamp(fin) - pd.Timestamp(debut)).total_seconds() / 3600
    n = len(perimetre)
    if n == 0 or duree_h <= 0:
        return {"disponibilite": None, "heures_arret": 0.0, "sites": n, "ecartes_a_verifier": 0, "sites_toute_la_periode": 0,
                "sites_avec_arret": 0}
    e = episodes[episodes["cle_site"].isin(perimetre)] if len(episodes) else episodes
    ecartes = 0
    par_site: dict[str, list] = {}
    for r in e.itertuples():
        a_verifier = bool(r.date_a_verifier) or pd.isna(r.debut)
        if a_verifier and pd.notna(r.fin) and not compter_dates_a_verifier:
            if pd.Timestamp(r.fin) > debut:
                ecartes += 1
            continue
        par_site.setdefault(r.cle_site, []).append((None if a_verifier and pd.isna(r.fin) else r.debut, r.fin))
    for k in a_l_arret_sans_episode & perimetre:
        par_site.setdefault(k, []).append((None, None))
    heures = {k: heures_indisponibles(v, debut, fin) for k, v in par_site.items()}
    total = sum(heures.values())
    return {"disponibilite": 100 * (1 - total / (n * duree_h)), "heures_arret": total, "sites": n,
            "ecartes_a_verifier": ecartes, "sites_avec_arret": sum(1 for h in heures.values() if h > 0),
            "sites_toute_la_periode": sum(1 for h in heures.values() if h >= duree_h - 1e-6)}


def arrets_en_cours(episodes: pd.DataFrame, maintenant: pd.Timestamp) -> pd.DataFrame:
    """Arrêts sans remise en marche, avec leur durée en jours (absente si la date de début est inconnue)."""
    e = episodes[episodes["fin"].isna()].copy()
    e["duree_j"] = ((pd.Timestamp(maintenant) - e["debut"]).dt.total_seconds() / 86400).round(1)
    return e.sort_values("debut", na_position="first").reset_index(drop=True)


def duree_mediane_arrets(episodes: pd.DataFrame) -> dict:
    """Durée médiane (jours) des arrêts terminés aux dates fiables ; les autres sont comptés à part."""
    clos = episodes[episodes["fin"].notna()]
    ok = clos[clos["debut"].notna() & ~clos["date_a_verifier"].astype(bool) & (clos["fin"] >= clos["debut"])]
    d = (ok["fin"] - ok["debut"]).dt.total_seconds() / 86400
    return {"mediane_j": float(d.median()) if len(d) else None, "retenus": int(len(d)), "ecartes": int(len(clos) - len(d))}


def arrets_par_mois(occurrences: pd.DataFrame, annee: int) -> pd.DataFrame:
    """Occurrences d'arrêt et sites distincts pour chaque mois de l'année (les 12 mois sont toujours présents)."""
    o = occurrences[occurrences["date"].dt.year == annee]
    g_ = o.groupby(o["date"].dt.month)
    t = pd.DataFrame({"Arrêts": g_.size(), "Sites distincts": g_["cle_site"].nunique()}).reindex(range(1, 13), fill_value=0)
    return t.assign(Mois=MOIS_COURTS).reset_index(drop=True)[["Mois", "Arrêts", "Sites distincts"]]


def arrets_par_an(occurrences: pd.DataFrame) -> pd.DataFrame:
    g_ = occurrences.groupby(occurrences["date"].dt.year)
    t = pd.DataFrame({"Arrêts": g_.size(), "Sites distincts": g_["cle_site"].nunique()})
    return t.reset_index(names="Année").astype({"Année": int}) if len(t) else pd.DataFrame(columns=["Année", "Arrêts", "Sites distincts"])


def matrice_arrets(occurrences: pd.DataFrame, sites: pd.DataFrame, annee: int) -> pd.DataFrame:
    """Par site : total d'arrêts de chaque année, puis détail par mois de l'année choisie. Sites triés du plus
    au moins touché sur l'année choisie ; seuls les sites ayant au moins une occurrence apparaissent."""
    o = occurrences[occurrences["cle_site"].isin(set(sites["cle_site"]))]
    if o.empty:
        return pd.DataFrame()
    an = pd.crosstab(o["cle_site"], o["date"].dt.year)
    an.columns = [f"Total {int(c)}" for c in an.columns]
    oa = o[o["date"].dt.year == annee]
    mois = pd.crosstab(oa["cle_site"], oa["date"].dt.month).reindex(columns=range(1, 13), fill_value=0)
    mois.columns = [f"{m} {str(annee)[-2:]}" for m in MOIS_COURTS]
    info = sites.drop_duplicates("cle_site").set_index("cle_site")[["site", "region", "phase"]].rename(
        columns={"site": "Site", "region": "Région", "phase": "Phase"})
    t = info.join(an, how="inner").join(mois).fillna(0)
    num = [c for c in t.columns if c not in ("Site", "Région", "Phase")]
    t[num] = t[num].astype(int)
    tri = f"Total {annee}" if f"Total {annee}" in t.columns else num[-1]
    return t.sort_values([tri, "Site"], ascending=[False, True]).reset_index(drop=True)


def causes_arrets(episodes: pd.DataFrame) -> pd.DataFrame:
    c = episodes["cause"].map(lambda x: "Non précisée" if est_vide(x) else str(x).strip())
    return c.value_counts().rename_axis("Cause").reset_index(name="Arrêts")


def duree_arret_par_equipe(episodes: pd.DataFrame, maintenant: pd.Timestamp) -> pd.DataFrame:
    """Durée cumulée d'arrêt (jours) des sites par équipe intervenante ; les arrêts en cours comptent jusqu'à
    maintenant ; ceux sans début connu ou sans équipe ne peuvent pas être attribués."""
    e = episodes[episodes["debut"].notna() & ~episodes["equipe"].map(est_vide)]
    d = ((e["fin"].fillna(pd.Timestamp(maintenant)) - e["debut"]).dt.total_seconds() / 86400).clip(lower=0)
    t = d.groupby(e["equipe"].astype(str).str.strip()).agg(["sum", "size"]).rename(columns={"sum": "Jours d'arrêt", "size": "Arrêts"})
    return t.sort_values("Jours d'arrêt", ascending=False).reset_index(names="Équipe")


# ============================================================================= lot 4 : visites et équipes
TYPES_VISITE = ["Maintenance préventive", "Maintenance corrective", "Urgence", "Inspection"]
COLONNES_VISITES = ["id", "cle_site", "site", "date", "chef", "membres", "equipe", "type", "etat_constate", "observations",
                    "source", "auteur", "horodatage"]
COLONNES_EQUIPES = ["nom", "zone", "chef", "telephone", "statut", "membres"]
STATUTS_EQUIPE = ["Active", "Inactive"]
TYPES_MISSION = {"Maintenance préventive": "Préventive", "Maintenance corrective": "Corrective",
                 "Inspection": "Réglementaire / inspection"}
SANS_CHEF = "— (chef non renseigné)"


def cle_nom(x) -> str:
    """Clé de rapprochement d'un nom de personne : sans accents, sans casse, espaces et ponctuation ignorés.
    « TIAM TIAGHOUE  Valery » et « Tiam Tiaghoue Valéry » ont la même clé ; deux orthographes différentes
    (« Ngangdi » / « Ngangndi ») ne l'ont pas : seule une correspondance validée les réunit."""
    import re
    import unicodedata
    if est_vide(x):
        return ""
    t = unicodedata.normalize("NFKD", str(x)).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", t).split())


def nom_retenu(x, correspondances: dict | None = None):
    """Nom affiché pour une personne : celui de la table de correspondance VALIDÉE s'il existe, sinon le nom
    tel que saisi (espaces nettoyés). Rien n'est fusionné sans validation."""
    if est_vide(x):
        return None
    propre = " ".join(str(x).split())
    return (correspondances or {}).get(cle_nom(propre), propre)


def variantes_de_noms(noms, correspondances: dict | None = None) -> list[list[str]]:
    """Groupes de noms écrits différemment mais identiques à la casse, aux accents et aux espaces près, et pas
    encore couverts par la table de correspondance : des PROPOSITIONS à valider."""
    groupes: dict[str, set] = {}
    for x in noms:
        if not est_vide(x):
            groupes.setdefault(cle_nom(x), set()).add(" ".join(str(x).split()))
    deja = correspondances or {}
    return sorted(sorted(v) for k, v in groupes.items() if len(v) > 1 and k not in deja)


def decouper_intervenants(texte) -> tuple[str | None, str | None]:
    """« A, B , C » → (« A », « B, C ») : le premier nom cité est pris comme chef d'équipe, les autres comme membres."""
    if est_vide(texte):
        return None, None
    noms = [" ".join(n.split()) for n in str(texte).replace(";", ",").split(",") if n.strip()]
    return (noms[0], ", ".join(noms[1:]) or None) if noms else (None, None)


def controler_visite(site, date, chef, type_visite, aujourd_hui: pd.Timestamp) -> list[str]:
    err = []
    if est_vide(site):
        err.append("Choisis la centrale visitée.")
    if date is None or pd.isna(date):
        err.append("Renseigne la date de la visite.")
    elif pd.Timestamp(date).normalize() > pd.Timestamp(aujourd_hui).normalize():
        err.append("La date de la visite ne peut pas être dans le futur.")
    if est_vide(chef):
        err.append("Renseigne le chef d'équipe.")
    if type_visite not in TYPES_VISITE:
        err.append("Choisis le type de visite.")
    return err


def filtrer_visites(v: pd.DataFrame, annee: int | None = None, mois: int | None = None, sites: set | None = None) -> pd.DataFrame:
    if annee is not None:
        v = v[v["date"].dt.year == annee]
    if mois is not None:
        v = v[v["date"].dt.month == mois]
    if sites is not None:
        v = v[v["cle_site"].isin(sites)]
    return v


def couverture_visites(v: pd.DataFrame, perimetre: set) -> dict:
    """Indicateurs de couverture sur les visites fournies (déjà filtrées) et le périmètre de centrales."""
    vp = v[v["cle_site"].isin(perimetre)]
    vues = set(vp["cle_site"])
    types = v["type"].value_counts()
    return {"visites": len(v), "centrales": v["cle_site"].nunique(), "centrales_perimetre": len(vues),
            "couverture": 100 * len(vues) / len(perimetre) if perimetre else None,
            "jamais": len(perimetre - vues), "chefs": int(v["chef"].dropna().nunique()),
            "sans_chef": int(v["chef"].isna().sum()),
            "preventives": int(types.get("Maintenance préventive", 0) + types.get("Inspection", 0)),
            "correctives": int(types.get("Maintenance corrective", 0)), "urgences": int(types.get("Urgence", 0))}


def visites_par_chef(v: pd.DataFrame) -> pd.DataFrame:
    """Visites, sites distincts et dernière visite par chef d'équipe ; les visites sans chef restent visibles."""
    g_ = v.assign(_c=v["chef"].fillna(SANS_CHEF)).groupby("_c")
    t = pd.DataFrame({"Visites": g_.size(), "Sites distincts": g_["cle_site"].nunique(), "Dernière visite": g_["date"].max()})
    return t.sort_values(["Visites", "Sites distincts"], ascending=False).reset_index(names="Chef d'équipe")


def visites_par_mois(v: pd.DataFrame) -> pd.DataFrame:
    m = v["date"].dt.to_period("M").dt.to_timestamp()
    g_ = v.groupby(m)
    return pd.DataFrame({"Visites": g_.size(), "Sites distincts": g_["cle_site"].nunique()}).reset_index(names="Mois")


# ----------------------------------------------------------------------------- équipes et missions
def controler_equipe(v: dict, noms_existants: set | None = None) -> list[str]:
    err = []
    if est_vide(v.get("nom")):
        err.append("Renseigne le nom de l'équipe.")
    elif noms_existants and cle_nom(v["nom"]) in {cle_nom(x) for x in noms_existants}:
        err.append("Une équipe porte déjà ce nom.")
    if est_vide(v.get("zone")):
        err.append("Renseigne la zone de l'équipe.")
    if est_vide(v.get("chef")):
        err.append("Renseigne le chef d'équipe.")
    if v.get("statut") not in STATUTS_EQUIPE:
        err.append("Statut inconnu.")
    tel = v.get("telephone")
    if not est_vide(tel) and sum(ch.isdigit() for ch in str(tel)) < 8:
        err.append("Le numéro de téléphone semble incomplet.")
    return err


def liste_membres(texte) -> list[str]:
    return [] if est_vide(texte) else [" ".join(m.split()) for m in str(texte).replace(";", ",").split(",") if m.strip()]


def missions_depuis_bi(bi: pd.DataFrame, noms_equipes: set, statuts_ouverts: list[str], aujourd_hui: pd.Timestamp) -> pd.DataFrame:
    """Missions = bons d'intervention ayant une date prévue et affectés à une équipe déclarée.
    Statut de mission : « Réalisée » (terminé ou clôturé), « En retard » (ouvert, date dépassée), « À venir »."""
    cols = ["id", "date_prevue", "site", "equipe", "type", "description", "statut_bi", "statut", "date_fin"]
    if bi is None or bi.empty or not noms_equipes:
        return pd.DataFrame(columns=cols)
    b = bi[bi["equipe"].isin(noms_equipes) & bi["date_prevue"].notna() & (bi["statut"] != "Annulé")]
    auj = pd.Timestamp(aujourd_hui).normalize()
    statut = ["Réalisée" if s_ in ("Terminé", "Clôturé") else ("En retard" if pd.Timestamp(d).normalize() < auj else "À venir")
              for s_, d in zip(b["statut"], b["date_prevue"])]
    return pd.DataFrame({"id": b["id"], "date_prevue": pd.to_datetime(b["date_prevue"]), "site": b["site"], "equipe": b["equipe"],
                         "type": b["type"], "description": b["description"], "statut_bi": b["statut"], "statut": statut,
                         "date_fin": pd.to_datetime(b["date_fin"])})[cols].reset_index(drop=True)


def taux_realisation(missions: pd.DataFrame, aujourd_hui: pd.Timestamp, jours: int = 30) -> dict:
    """Part des missions ÉCHUES sur la fenêtre (date prévue dans les `jours` derniers jours, aujourd'hui exclu)
    qui ont été réalisées."""
    auj = pd.Timestamp(aujourd_hui).normalize()
    d = missions["date_prevue"].dt.normalize() if len(missions) else pd.Series(dtype="datetime64[ns]")
    e = missions[(d >= auj - pd.Timedelta(days=jours)) & (d < auj)] if len(missions) else missions
    return {"echues": len(e), "realisees": int((e["statut"] == "Réalisée").sum()) if len(e) else 0,
            "taux": 100 * (e["statut"] == "Réalisée").mean() if len(e) else None}


def indicateurs_equipes(equipes: pd.DataFrame, missions: pd.DataFrame, zones_du_parc: set, aujourd_hui: pd.Timestamp) -> dict:
    act = equipes[equipes["statut"] == "Active"] if len(equipes) else equipes
    personnes = set()
    for r in act.itertuples():
        personnes |= {cle_nom(r.chef)} | {cle_nom(m) for m in liste_membres(r.membres)}
    personnes.discard("")
    zones = {str(z) for z in act["zone"].dropna()} if len(act) else set()
    return {"actives": len(act), "inactives": len(equipes) - len(act), "personnes": len(personnes),
            "zones_couvertes": len(zones & zones_du_parc) if zones_du_parc else len(zones), "zones": len(zones_du_parc),
            "a_venir": int((missions["statut"] == "À venir").sum()) if len(missions) else 0,
            "en_retard": int((missions["statut"] == "En retard").sum()) if len(missions) else 0,
            **{f"realisation_{k}": v for k, v in taux_realisation(missions, aujourd_hui).items()}}


def tableau_equipes(equipes: pd.DataFrame, visites: pd.DataFrame, missions: pd.DataFrame, sites: pd.DataFrame,
                    fiches_par_equipe: dict, aujourd_hui: pd.Timestamp, mois: int = 12) -> pd.DataFrame:
    """Une ligne par équipe déclarée. Une visite est attribuée à l'équipe si elle porte son nom, ou si son chef
    est le chef de l'équipe. Sites affectés : centrales dont le responsable de zone est le chef de l'équipe."""
    debut = pd.Timestamp(aujourd_hui).normalize() - pd.DateOffset(months=mois)
    resp = sites["responsable"].map(cle_nom) if len(sites) else pd.Series(dtype=str)
    lignes = []
    for r in equipes.itertuples():
        kc = cle_nom(r.chef)
        v = visites[(visites["equipe"] == r.nom) | (visites["chef"].map(cle_nom) == kc)] if len(visites) else visites
        v12 = v[v["date"] >= debut] if len(v) else v
        m = missions[missions["equipe"] == r.nom] if len(missions) else missions
        nb = lambda s_: int((m["statut"] == s_).sum()) if len(m) else 0  # noqa: E731
        dates = [x for x in ([v["date"].max()] if len(v) else []) + ([m["date_fin"].max()] if len(m) else []) if pd.notna(x)]
        lignes.append({"Équipe": r.nom, "Zone": r.zone, "Chef": r.chef, "Téléphone": r.telephone, "Statut": r.statut,
                       "Membres": len(liste_membres(r.membres)), "Sites affectés": int((resp == kc).sum()) if kc else 0,
                       f"Interventions {mois} mois": len(v12), "Sites visités": v12["cle_site"].nunique() if len(v12) else 0,
                       "Missions à venir": nb("À venir"), "Missions en retard": nb("En retard"), "Missions réalisées": nb("Réalisée"),
                       "Fiches saisies": int(fiches_par_equipe.get(r.nom, 0)),
                       "Dernière activité": max(dates) if dates else pd.NaT})
    return pd.DataFrame(lignes)


def chefs_sans_equipe(visites: pd.DataFrame, equipes: pd.DataFrame, zone_par_site: dict | None = None) -> pd.DataFrame:
    """Chefs présents dans l'historique des visites mais chefs d'aucune équipe déclarée (ni membres d'une équipe)."""
    connus = set()
    for r in equipes.itertuples():
        connus |= {cle_nom(r.chef)} | {cle_nom(m) for m in liste_membres(r.membres)}
    v = visites[visites["chef"].notna()] if len(visites) else visites
    if v.empty:
        return pd.DataFrame(columns=["Chef", "Visites", "Zone principale", "Dernière"])
    v = v[~v["chef"].map(cle_nom).isin(connus)]
    if v.empty:
        return pd.DataFrame(columns=["Chef", "Visites", "Zone principale", "Dernière"])
    z = v["cle_site"].map(zone_par_site or {})
    g_ = v.assign(_z=z).groupby("chef")
    t = pd.DataFrame({"Visites": g_.size(), "Zone principale": g_["_z"].agg(lambda s_: s_.dropna().mode().iloc[0] if s_.notna().any() else None),
                      "Dernière": g_["date"].max()})
    return t.sort_values("Visites", ascending=False).reset_index(names="Chef")


def maintenant_douala() -> pd.Timestamp:
    from zoneinfo import ZoneInfo
    return pd.Timestamp(datetime.now(ZoneInfo("Africa/Douala")).replace(tzinfo=None)).normalize()
