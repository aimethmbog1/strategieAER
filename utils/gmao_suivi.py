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
    s["zone"], s["responsable"] = None, None
    if aff is not None and not aff.empty:
        a = aff.sort_values("annee").assign(cle_site=aff["site"].map(g.cle)).drop_duplicates("cle_site", keep="last").set_index("cle_site")
        s["zone"], s["responsable"] = s["cle_site"].map(a["zone"]), s["cle_site"].map(a["responsable"])
    s = gi.appliquer_etats_saisis(s[cols].reset_index(drop=True), etats_saisis())
    if bi is not None and len(bi):
        # Un bon d'intervention correctif ouvert « centrale à l'arrêt » impose l'arrêt, sauf si un état a été
        # saisi APRÈS la date d'arrêt du bon : l'information la plus récente l'emporte.
        o = bi[bi["statut"].isin(gc.STATUTS_BI_OUVERTS) & bi["centrale_arret"]]
        if o.empty:
            return s, absents
        d = o.assign(cle_site=o["site"].map(g.cle), _d=pd.to_datetime(o["date_arret"].fillna(o["date_creation"]))).groupby("cle_site")["_d"].max()
        dbi = pd.to_datetime(s["cle_site"].map(d.to_dict()))
        m = s["cle_site"].isin(d.index) & (s["etat"] != gi.ARRET) & ~(s["etat_date"].notna() & dbi.notna() & (s["etat_date"] > dbi))
        s.loc[m, "cause"] = "Bon d'intervention ouvert : centrale à l'arrêt"
        s.loc[m, "etat"], s.loc[m, "etat_source"] = gi.ARRET, "Bon d'intervention"
        s.loc[m, "etat_date"] = dbi[m]
    return s, absents


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
    es = etats_saisis()
    if len(es):   # un état « à l'arrêt » saisi dans l'application est une occurrence d'arrêt datée
        e = es[es["etat"] == gi.ARRET]
        a = pd.concat([a, pd.DataFrame({"cle_site": e["cle_site"], "date": e["date_effet"]})], ignore_index=True)
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


# ============================================================================= lot 2 : écritures
REGISTRE_ETATS = "gmao_etats_saisis"


def etats_saisis() -> pd.DataFrame:
    """États de centrales saisis dans l'application (historique complet, jamais écrasé). Registre distinct des
    journaux importés : réimporter un journal remplace toute son année et effacerait ces saisies."""
    from .storage import session_ou_stockage
    d = session_ou_stockage(REGISTRE_ETATS, lambda: pd.DataFrame(columns=gi.COLONNES_ETATS_SAISIS))
    d = pd.DataFrame(columns=gi.COLONNES_ETATS_SAISIS) if d is None or len(d) == 0 else d.copy()
    for c in gi.COLONNES_ETATS_SAISIS:
        if c not in d.columns:
            d[c] = None
    for c in ("horodatage", "date_effet"):
        d[c] = pd.to_datetime(d[c], errors="coerce")
    return d[gi.COLONNES_ETATS_SAISIS]


def _auteur() -> str:
    try:
        from .auth import utilisateur
        u = utilisateur() or {}
        return u.get("nom") or u.get("login") or "?"
    except Exception:  # noqa: BLE001
        return "?"


def enregistrer_etat(site: str, etat: str, cause: str | None, date_effet, commentaire: str | None,
                     aujourd_hui: pd.Timestamp) -> bool:
    """Ajoute un état saisi pour une centrale (contrôlé, tracé au journal de l'application)."""
    err = gi.controler_etat(site, etat, date_effet, aujourd_hui, cause)
    if err:
        raise ValueError("\n".join(err))
    from .storage import mettre_a_jour
    ligne = {"horodatage": pd.Timestamp(gc.maintenant()), "cle_site": g.cle(site), "site": str(site).strip(), "etat": etat,
             "cause": None if gi.est_vide(cause) else str(cause).strip(), "date_effet": pd.Timestamp(date_effet).normalize(),
             "commentaire": None if gi.est_vide(commentaire) else str(commentaire).strip(), "auteur": _auteur()}
    d = pd.concat([etats_saisis(), pd.DataFrame([ligne])], ignore_index=True)
    return mettre_a_jour(REGISTRE_ETATS, d, f"état de la centrale {ligne['site']} : {etat} au {ligne['date_effet']:%d/%m/%Y}")


def creer_fiche(v: dict, aujourd_hui: pd.Timestamp) -> str:
    """Crée une fiche de défaut : c'est un bon d'intervention correctif du GMAO, enrichi du matériel et des
    quantités. Renvoie son identifiant. `v` : champs de gi.controler_fiche + site_id, phase, region,
    etat_arrivee, statut, equipe, chef, mesure_prise."""
    err = gi.controler_fiche(v, aujourd_hui)
    if err:
        raise ValueError("\n".join(err))
    constat = pd.Timestamp(v["date_constat"]).normalize()
    ech = gi.echeance(constat, v["priorite"], delais(), v.get("jours_prevus"))
    arret = v.get("etat_arrivee") == "À l'arrêt"
    cloturee = bool(v.get("cloturee"))
    ligne = {
        "origine": "Suivi de la maintenance", "type": "Corrective", "priorite": gi.PRIORITE_VERS_BI[v["priorite"]],
        "site_id": v.get("site_id"), "site": str(v["site"]).strip(), "phase": v.get("phase"), "region": v.get("region"),
        "systeme": v["categorie"], "equipement": str(v["materiel"]).strip(), "description": str(v["description"]).strip(),
        "statut": "Clôturé" if cloturee else (v.get("statut") or "À planifier"), "centrale_arret": arret,
        "date_creation": constat, "date_prevue": ech, "date_arret": constat if arret else None,
        "date_fin": pd.Timestamp(v["date_cloture"]).normalize() if cloturee else None,
        "equipe": None if gi.est_vide(v.get("equipe")) else v["equipe"], "chef": None if gi.est_vide(v.get("chef")) else v["chef"],
        "travaux": None if gi.est_vide(v.get("mesure_prise")) else str(v["mesure_prise"]).strip(),
        "qte_affectee": float(v.get("qte_affectee") or 0), "qte_remplacee": float(v.get("qte_remplacee") or 0)}
    return gc.ajouter("gmao_bi", [ligne], "BI", f"fiche de défaut — {ligne['site']} : {ligne['equipement']} ({v['priorite']})")[0]


def maj_fiche_application(ident: str, statut: str, qte_remplacee: float, mesure_prise: str | None, date_cloture,
                          aujourd_hui: pd.Timestamp) -> None:
    """Met à jour une fiche saisie dans l'application (bon d'intervention)."""
    bi = gc.table("gmao_bi")
    l = bi[bi["id"].astype(str) == str(ident)]
    if l.empty:
        raise ValueError("Fiche introuvable.")
    l = l.iloc[0]
    ferme = statut in ("Terminé", "Clôturé")
    err = _controler_cloture(l["date_creation"], ferme, date_cloture, qte_remplacee, l["qte_affectee"], aujourd_hui)
    if statut not in gc.STATUTS_BI:
        err.append("Statut inconnu.")
    if err:
        raise ValueError("\n".join(err))
    val = {"statut": statut, "qte_remplacee": float(qte_remplacee or 0),
           "date_fin": pd.Timestamp(date_cloture).normalize() if ferme else None}
    if not gi.est_vide(mesure_prise):
        val["travaux"] = str(mesure_prise).strip()
    if ferme and bool(l["centrale_arret"]) and pd.isna(l["date_remise"]):
        val["date_remise"] = val["date_fin"]
    gc.modifier("gmao_bi", ident, val, f"fiche {ident} mise à jour : {statut}")


def _controler_cloture(date_constat, ferme: bool, date_cloture, qte_remplacee, qte_affectee, aujourd_hui) -> list[str]:
    err = []
    if (qte_remplacee or 0) < 0:
        err.append("La quantité remplacée ne peut pas être négative.")
    elif pd.notna(qte_affectee) and qte_affectee and (qte_remplacee or 0) > qte_affectee:
        err.append("La quantité remplacée dépasse la quantité affectée.")
    if ferme:
        if date_cloture is None or pd.isna(date_cloture):
            err.append("Renseigne la date de clôture.")
        else:
            c = pd.Timestamp(date_cloture).normalize()
            if c > pd.Timestamp(aujourd_hui).normalize():
                err.append("La date de clôture ne peut pas être dans le futur.")
            if pd.notna(date_constat) and c < pd.Timestamp(date_constat).normalize():
                err.append("La date de clôture précède la date de constat.")
    return err


def maj_fiche_journal(ligne: int, site: str, cloturer: bool, qte_remplacee: float, mesure: str | None, date_cloture,
                      aujourd_hui: pd.Timestamp) -> None:
    """Met à jour une fiche issue d'un journal importé, directement dans le registre des défauts.
    Garde-fou : la ligne visée doit toujours porter le même site (le registre a pu être réimporté entre-temps)."""
    from .storage import mettre_a_jour
    t = gmao_ui.charger_tables()
    d = t.get("defauts")
    if d is None or ligne not in d.index or g.cle(d.at[ligne, "site"]) != g.cle(site):
        raise ValueError("La fiche a changé depuis l'affichage (journal réimporté ?) : recharge la page.")
    err = _controler_cloture(pd.to_datetime(d.at[ligne, "date_incident"], errors="coerce"), cloturer, date_cloture,
                             qte_remplacee, pd.to_numeric(d.at[ligne, "qte_affectee"], errors="coerce"), aujourd_hui)
    if err:
        raise ValueError("\n".join(err))
    d = d.copy()
    d.at[ligne, "qte_remplacee"] = float(qte_remplacee or 0)
    if not gi.est_vide(mesure):
        d.at[ligne, "mesure"] = str(mesure).strip()
    if cloturer:
        d.at[ligne, "resultat"] = "Clôturé"
        d.at[ligne, "date_achevement"] = pd.Timestamp(date_cloture).normalize()
    note = f"Mis à jour dans l'application le {pd.Timestamp(aujourd_hui):%d/%m/%Y} par {_auteur()}"
    ancien = d.at[ligne, "commentaire"]
    d.at[ligne, "commentaire"] = note if gi.est_vide(ancien) else f"{ancien} — {note}"
    if mettre_a_jour(gmao_ui.TABLES["defauts"], d, f"fiche du {d.at[ligne, 'source']} — {site} : "
                     + ("clôturée" if cloturer else "mise à jour")):
        t["defauts"] = d
