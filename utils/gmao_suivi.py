"""Suivi de la maintenance — accès aux données : assemble, à partir des registres existants du GMAO
(journaux importés, bons d'intervention, inspections, affectations, supervision), les tableaux attendus par
les fonctions pures de utils/gmao_indicateurs.py. Aucune table nouvelle n'est créée ici."""
from __future__ import annotations

import copy

import pandas as pd

from . import gmao as g
from . import gmao_core as gc
from . import gmao_indicateurs as gi
from . import gmao_ui
from .parametres import memoriser, valeur

PAGE = "suivi_maintenance"


# ----------------------------------------------------------------------------- paramètres (jamais en dur)
def delais() -> dict:
    d = valeur(PAGE, "delais", None)
    base = dict(gi.DELAIS_DEFAUT)
    if isinstance(d, dict):
        base.update({k: (None if v in (None, "") else int(v)) for k, v in d.items() if k in base})
    return base


def poids() -> dict:
    p = copy.deepcopy(gi.POIDS_DEFAUT)
    s = valeur(PAGE, "poids", None)
    if isinstance(s, dict):
        for k, v in s.items():
            if isinstance(v, dict) and isinstance(p.get(k), dict):
                p[k].update(v)
            elif k in p:
                p[k] = v
    return p


def reglage(cle: str, defaut):
    return valeur(PAGE, cle, defaut)


def enregistrer_reglages(valeurs: dict) -> None:
    from .auth import journaliser
    for k, v in valeurs.items():
        memoriser(PAGE, k, v)
    journaliser("paramètres", f"suivi de la maintenance : {', '.join(valeurs)} mis à jour")


# ----------------------------------------------------------------------------- tableaux
def sites_suivis(ref_sites: pd.DataFrame, bi: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Une ligne par centrale : Phases 1 et 2 d'après le dernier état connu des journaux (c'est lui qui porte
    l'état de fonctionnement), Phase 3 d'après le référentiel (« Non mis en service »). Un bon d'intervention
    correctif ouvert « centrale à l'arrêt » impose l'état « À l'arrêt » (règle déjà appliquée par le GMAO).
    Renvoie aussi les sites des journaux absents du référentiel (orthographe différente)."""
    t = gmao_ui.charger_tables()
    st_ = g.statuts_courants(t.get("statuts"))
    aff = t.get("affectations")
    cols = ["cle_site", "site", "phase", "region", "kwc", "etat", "cause", "zone", "responsable"]
    lignes, absents = [], []
    cles_ref = set(ref_sites["Nom du site"].map(g.cle))
    if not st_.empty:
        s = pd.DataFrame({"cle_site": st_["cle_site"], "site": st_["site"], "phase": st_["phase"], "region": st_["region"],
                          "kwc": pd.to_numeric(st_["puissance_kwc"], errors="coerce").fillna(0),
                          "etat": st_["etat"].map(gi.etat_detaille), "cause": st_["causes"] if "causes" in st_ else None})
        lignes.append(s)
        absents = sorted(st_.loc[~st_["cle_site"].isin(cles_ref), "site"])
    deja = set(lignes[0]["cle_site"]) if lignes else set()
    r3 = ref_sites[ref_sites["Phase"].astype(str).str.contains("3")] if lignes else ref_sites
    r3 = r3.assign(cle_site=r3["Nom du site"].map(g.cle))
    r3 = r3[~r3["cle_site"].isin(deja)].drop_duplicates("cle_site")
    lignes.append(pd.DataFrame({"cle_site": r3["cle_site"], "site": r3["Nom du site"], "phase": r3["Phase"],
                                "region": r3["Région"], "kwc": pd.to_numeric(r3["Puissance (kWc)"], errors="coerce").fillna(0),
                                "etat": gi.NON_MES if not st_.empty else gi.NON_RENSEIGNE, "cause": None}))
    s = pd.concat(lignes, ignore_index=True).drop_duplicates("cle_site")
    if bi is not None and len(bi):
        arr = set(bi.loc[bi["statut"].isin(gc.STATUTS_BI_OUVERTS) & bi["centrale_arret"], "site"].map(g.cle))
        m = s["cle_site"].isin(arr) & (s["etat"] != gi.ARRET)
        s.loc[m, "cause"] = "Bon d'intervention ouvert : centrale à l'arrêt"
        s.loc[m, "etat"] = gi.ARRET
    s["zone"], s["responsable"] = None, None
    if aff is not None and not aff.empty:
        a = aff.sort_values("annee").assign(cle_site=aff["site"].map(g.cle)).drop_duplicates("cle_site", keep="last").set_index("cle_site")
        s["zone"], s["responsable"] = s["cle_site"].map(a["zone"]), s["cle_site"].map(a["responsable"])
    return s[cols].reset_index(drop=True), absents


def fiches(aujourd_hui: pd.Timestamp, bi: pd.DataFrame) -> pd.DataFrame:
    t = gmao_ui.charger_tables()
    j = gi.fiches_depuis_journaux(g.normaliser_defauts(t.get("defauts")))
    b = gi.fiches_depuis_bi(bi, gc.STATUTS_BI_OUVERTS)
    tout = pd.concat([x for x in (j, b) if len(x)], ignore_index=True) if len(j) or len(b) else j
    return gi.completer_fiches(tout, aujourd_hui, delais())


def arrets_connus(f: pd.DataFrame, bi: pd.DataFrame) -> pd.DataFrame:
    """Occurrences d'arrêt connues à ce stade : fiches constatant le site à l'arrêt et bons d'intervention avec
    date d'arrêt — une seule occurrence par site et par jour. (Les épisodes d'arrêt datés arrivent au lot 3.)"""
    a = f.loc[f["site_arret_au_constat"] & f["date_constat"].notna(), ["cle_site", "date_constat"]].rename(columns={"date_constat": "date"})
    if bi is not None and len(bi):
        b = bi[bi["centrale_arret"] & bi["date_arret"].notna()]
        a = pd.concat([a, pd.DataFrame({"cle_site": b["site"].map(g.cle), "date": b["date_arret"]})], ignore_index=True)
    a["date"] = pd.to_datetime(a["date"]).dt.normalize()
    return a.drop_duplicates().reset_index(drop=True)


def visites_connues(f: pd.DataFrame, bi: pd.DataFrame) -> pd.DataFrame:
    """Passages d'une équipe sur site connus à ce stade : inspections importées, constats de défaut (l'équipe
    était sur place) et bons d'intervention terminés — une occurrence par site et par jour, avec sa source."""
    t = gmao_ui.charger_tables()
    lots = []
    ins = t.get("inspections")
    if ins is not None and not ins.empty:
        lots.append(pd.DataFrame({"cle_site": ins["site"].map(g.cle), "date": pd.to_datetime(ins["date_inspection"], errors="coerce"),
                                  "source": "Inspection"}))
    lots.append(pd.DataFrame({"cle_site": f["cle_site"], "date": f["date_constat"], "source": "Constat de défaut"}))
    if bi is not None and len(bi):
        b = bi[bi["date_fin"].notna()]
        lots.append(pd.DataFrame({"cle_site": b["site"].map(g.cle), "date": b["date_fin"], "source": "Bon d'intervention"}))
    v = pd.concat(lots, ignore_index=True)
    v["date"] = pd.to_datetime(v["date"]).dt.normalize()
    return v.dropna(subset=["date"]).drop_duplicates(["cle_site", "date"]).reset_index(drop=True)


def supervision_deconnectee(seuil_jours: int) -> dict[str, pd.Timestamp]:
    """Centrales suivies par la supervision dont la dernière donnée est plus ancienne que le seuil (en jours),
    par rapport à la donnée la plus récente reçue. Clé : nom de centrale normalisé ; valeur : dernière donnée."""
    from .storage import charger
    sup = charger("supervision_mesures")
    if sup is None or sup.empty:
        return {}
    d = pd.to_datetime(sup["Date"], errors="coerce")
    der = d.groupby(sup["Centrale"].map(g.cle)).max()
    return {k: v for k, v in der.items() if pd.notna(v) and (d.max() - v).days > seuil_jours}
