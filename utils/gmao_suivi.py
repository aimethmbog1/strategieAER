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
    ep = arrets_declares()
    if len(ep):   # arrêts déclarés sur la plateforme (ceux dont le début est inconnu ne peuvent pas être datés)
        ep = ep[ep["debut"].notna()]
        a = pd.concat([a, pd.DataFrame({"cle_site": ep["cle_site"], "date": ep["debut"]})], ignore_index=True)
    a["date"] = pd.to_datetime(a["date"]).dt.normalize()
    return a.drop_duplicates().reset_index(drop=True)


def correspondances_noms() -> dict:
    """Table de correspondance VALIDÉE des noms de chefs d'équipe : clé normalisée → nom retenu."""
    d = valeur(PAGE, "noms_chefs", None)
    return d if isinstance(d, dict) else {}


def valider_correspondance(variantes: list[str], retenu: str) -> None:
    """Enregistre que ces écritures désignent la même personne, affichée sous le nom `retenu`."""
    if gi.est_vide(retenu):
        raise ValueError("Indique le nom à retenir.")
    d = dict(correspondances_noms())
    propre = " ".join(str(retenu).split())
    for x in list(variantes) + [propre]:
        if not gi.est_vide(x):
            d[gi.cle_nom(x)] = propre
    enregistrer_reglages({"noms_chefs": d})


def visites_connues(f: pd.DataFrame, bi: pd.DataFrame) -> pd.DataFrame:
    """Passages d'une équipe sur site : visites saisies, inspections importées, bons d'intervention terminés et
    constats de défaut (l'équipe était sur place). Une seule ligne par site et par jour : la source la plus
    détaillée est gardée (dans cet ordre). Les noms de chefs passent par la table de correspondance validée."""
    t = gmao_ui.charger_tables()
    cols = ["cle_site", "site", "date", "chef", "membres", "equipe", "type", "etat_constate", "observations", "source"]
    lots = []
    vs = visites_saisies()
    if len(vs):
        lots.append(vs.assign(source="Visite saisie")[cols])
    ins = t.get("inspections")
    if ins is not None and not ins.empty:
        qui = [gi.decouper_intervenants(x) for x in ins["inspecte_par"]]
        lots.append(pd.DataFrame({"cle_site": ins["site"].map(g.cle), "site": ins["site"], "date": pd.to_datetime(ins["date_inspection"], errors="coerce"),
                                  "chef": [q[0] for q in qui], "membres": [q[1] for q in qui], "equipe": None, "type": "Inspection",
                                  "etat_constate": None, "observations": ins["remarque"] if "remarque" in ins else None,
                                  "source": "Inspection importée (" + ins["annee"].astype(str) + ")"})[cols])
    if bi is not None and len(bi):
        b = bi[bi["date_fin"].notna()]
        if len(b):
            lots.append(pd.DataFrame({"cle_site": b["site"].map(g.cle), "site": b["site"], "date": b["date_fin"], "chef": b["chef"],
                                      "membres": b["intervenants"], "equipe": b["equipe"],
                                      "type": b["type"].map(lambda x: "Maintenance corrective" if x == "Corrective" else "Maintenance préventive"),
                                      "etat_constate": None, "observations": b["travaux"], "source": "Bon d'intervention " + b["id"].astype(str)})[cols])
    if len(f):
        lots.append(pd.DataFrame({"cle_site": f["cle_site"], "site": f["site"], "date": f["date_constat"], "chef": None, "membres": None,
                                  "equipe": None, "type": f["priorite"].map(lambda p: "Urgence" if p == "URGENT" else "Maintenance corrective"),
                                  "etat_constate": f["site_arret_au_constat"].map({True: gi.ARRET, False: None}),
                                  "observations": f["description"], "source": "Constat de défaut (" + f["source"].astype(str) + ")"})[cols])
    if not lots:
        return pd.DataFrame(columns=cols)
    v = pd.concat(lots, ignore_index=True)
    v["date"] = pd.to_datetime(v["date"]).dt.normalize()
    v = v.dropna(subset=["date"]).drop_duplicates(["cle_site", "date"]).reset_index(drop=True)
    corr = correspondances_noms()
    v["chef"] = v["chef"].map(lambda x: gi.nom_retenu(x, corr))
    return v


def interventions_sans_date(f: pd.DataFrame) -> int:
    """Interventions impossibles à situer dans le temps (fiches sans date de constat, inspections sans date) :
    elles n'entrent dans aucun filtre de période, mais elles sont comptées et affichées."""
    ins = gmao_ui.charger_tables().get("inspections")
    n_ins = 0 if ins is None or ins.empty else int(pd.to_datetime(ins["date_inspection"], errors="coerce").isna().sum())
    return int(f["date_constat"].isna().sum()) + n_ins


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
                     aujourd_hui: pd.Timestamp, synchroniser_arret: bool = True) -> bool:
    """Ajoute un état saisi pour une centrale (contrôlé, tracé au journal de l'application).

    Les arrêts suivent (sauf `synchroniser_arret=False`) : passer une centrale « À l'arrêt » ouvre un épisode
    d'arrêt s'il n'y en a pas en cours ; la repasser en service clôt l'épisode en cours à la date constatée."""
    err = gi.controler_etat(site, etat, date_effet, aujourd_hui, cause)
    ouvert = None
    if synchroniser_arret and not err:
        ep = arrets_declares()
        o = ep[(ep["cle_site"] == g.cle(site)) & ep["fin"].isna()]
        ouvert = o.iloc[0] if len(o) else None
        if ouvert is not None and etat != gi.ARRET and pd.notna(ouvert["debut"]) \
                and pd.Timestamp(date_effet).normalize() < pd.Timestamp(ouvert["debut"]).normalize():
            err.append(f"Un arrêt est en cours depuis le {ouvert['debut']:%d/%m/%Y} : la date constatée ne peut pas le précéder.")
    if err:
        raise ValueError("\n".join(err))
    from .storage import mettre_a_jour
    ligne = {"horodatage": pd.Timestamp(gc.maintenant()), "cle_site": g.cle(site), "site": str(site).strip(), "etat": etat,
             "cause": None if gi.est_vide(cause) else str(cause).strip(), "date_effet": pd.Timestamp(date_effet).normalize(),
             "commentaire": None if gi.est_vide(commentaire) else str(commentaire).strip(), "auteur": _auteur()}
    d = pd.concat([etats_saisis(), pd.DataFrame([ligne])], ignore_index=True)
    ok = mettre_a_jour(REGISTRE_ETATS, d, f"état de la centrale {ligne['site']} : {etat} au {ligne['date_effet']:%d/%m/%Y}")
    if ok and synchroniser_arret:
        if etat == gi.ARRET and ouvert is None:
            _ecrire_arret({"site": ligne["site"], "debut": ligne["date_effet"], "cause": ligne["cause"] or "Non précisée",
                           "commentaire": ligne["commentaire"], "source": "État saisi (date du constat)"})
        elif etat != gi.ARRET and ouvert is not None:
            fin = max(ligne["date_effet"], pd.Timestamp(ouvert["debut"])) if pd.notna(ouvert["debut"]) else ligne["date_effet"]
            _clore_arret(ouvert["id"], fin)
    return ok


def creer_fiche(v: dict, aujourd_hui: pd.Timestamp) -> str:
    """Crée une fiche de défaut : c'est un bon d'intervention correctif du GMAO, enrichi du matériel et des
    quantités. Renvoie son identifiant. `v` : champs de gi.controler_fiche + site_id, phase, region,
    etat_arrivee, statut, equipe, chef, mesure_prise."""
    err = gi.controler_fiche(v, aujourd_hui)
    if err:
        raise ValueError("\n".join(err))
    constat = pd.Timestamp(v["date_constat"]).normalize()
    ech = gi.echeance(constat, v["priorite"], delais(), v.get("jours_prevus"))
    arret = v.get("etat_arrivee") == "À l'arrêt" or bool(v.get("declarer_arret"))
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
    ident = gc.ajouter("gmao_bi", [ligne], "BI", f"fiche de défaut — {ligne['site']} : {ligne['equipement']} ({v['priorite']})")[0]
    if v.get("declarer_arret") and not cloturee:
        # l'arrêt lié à la fiche : le bon d'intervention « centrale à l'arrêt » porte déjà l'état du site
        ep = arrets_declares()
        if g.cle(ligne["site"]) not in set(ep.loc[ep["fin"].isna(), "cle_site"]):
            _ecrire_arret({"site": ligne["site"], "debut": constat, "cause": v.get("cause_arret") or "Non précisée",
                           "equipe": ligne["equipe"], "source": f"Fiche {ident}", "commentaire": ligne["description"][:200]})
    return ident


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
    if ferme:   # la clôture de la fiche vaut remise en marche pour l'arrêt déclaré avec elle
        ep = arrets_declares()
        lie = ep[(ep["source"] == f"Fiche {ident}") & ep["fin"].isna()]
        if len(lie):
            _clore_arret(lie.iloc[0]["id"], max(val["date_fin"], lie.iloc[0]["debut"]) if pd.notna(lie.iloc[0]["debut"]) else val["date_fin"])


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


# ============================================================================= lot 3 : épisodes d'arrêt
REGISTRE_ARRETS = "gmao_arrets"


def arrets_declares() -> pd.DataFrame:
    """Épisodes d'arrêt déclarés dans l'application : un début, une fin (vide tant que l'arrêt est en cours)."""
    from .storage import session_ou_stockage
    d = session_ou_stockage(REGISTRE_ARRETS, lambda: pd.DataFrame(columns=gi.COLONNES_ARRETS))
    d = pd.DataFrame(columns=gi.COLONNES_ARRETS) if d is None or len(d) == 0 else d.copy()
    for c in gi.COLONNES_ARRETS:
        if c not in d.columns:
            d[c] = None
    for c in ("debut", "fin", "horodatage"):
        d[c] = pd.to_datetime(d[c], errors="coerce")
    d["date_a_verifier"] = d["date_a_verifier"].fillna(False).astype(bool)
    return d[gi.COLONNES_ARRETS]


def _ecrire_arret(v: dict) -> str:
    from .storage import mettre_a_jour
    d = arrets_declares()
    an = gc.maintenant().year
    nums = d["id"].dropna().astype(str)
    nums = nums[nums.str.startswith(f"AR-{an}-")].str.split("-").str[-1].astype(int)
    ident = f"AR-{an}-{(nums.max() + 1 if len(nums) else 1):04d}"
    debut = None if v.get("debut") is None or pd.isna(v.get("debut")) else pd.Timestamp(v["debut"])
    ligne = {"id": ident, "cle_site": g.cle(v["site"]), "site": str(v["site"]).strip(), "debut": debut, "fin": None,
             "cause": str(v["cause"]).strip(), "commentaire": None if gi.est_vide(v.get("commentaire")) else str(v["commentaire"]).strip(),
             "equipe": None if gi.est_vide(v.get("equipe")) else str(v["equipe"]).strip(), "source": v.get("source") or "Saisie",
             "date_a_verifier": bool(v.get("date_a_verifier")) or debut is None, "auteur": _auteur(),
             "horodatage": pd.Timestamp(gc.maintenant()), "remise_par": None}
    d = pd.concat([d, pd.DataFrame([ligne])], ignore_index=True)
    mettre_a_jour(REGISTRE_ARRETS, d, f"arrêt {ident} déclaré — {ligne['site']} : {ligne['cause']}")
    return ident


def _clore_arret(ident: str, fin) -> None:
    from .storage import mettre_a_jour
    d = arrets_declares()
    i = d.index[d["id"].astype(str) == str(ident)]
    if len(i):
        d.loc[i[0], "fin"] = pd.Timestamp(fin)
        d.loc[i[0], "remise_par"] = _auteur()
        mettre_a_jour(REGISTRE_ARRETS, d, f"arrêt {ident} — {d.loc[i[0], 'site']} : remise en marche le {pd.Timestamp(fin):%d/%m/%Y %H:%M}")


def declarer_arret(site: str, debut, cause: str, commentaire: str | None = None, equipe: str | None = None,
                   source: str = "Saisie", mettre_a_l_arret: bool = True) -> str:
    """Déclare un arrêt de centrale. Par défaut, la centrale passe aussi « À l'arrêt » (état saisi)."""
    ep = arrets_declares()
    err = gi.controler_arret(site, debut, cause, gc.maintenant(), set(ep.loc[ep["fin"].isna(), "cle_site"]))
    if err:
        raise ValueError("\n".join(err))
    ident = _ecrire_arret({"site": site, "debut": debut, "cause": cause, "commentaire": commentaire, "equipe": equipe, "source": source})
    if mettre_a_l_arret:
        enregistrer_etat(site, gi.ARRET, cause, pd.Timestamp(debut).normalize(), f"Arrêt {ident}", gc.maintenant(),
                         synchroniser_arret=False)
    return ident


def remettre_en_marche(ident: str, fin, etat_apres: str | None = gi.H24) -> None:
    """Enregistre la remise en marche. La centrale repasse à `etat_apres` (None = ne pas toucher à son état)."""
    ep = arrets_declares()
    l = ep[ep["id"].astype(str) == str(ident)]
    if l.empty or pd.notna(l.iloc[0]["fin"]):
        raise ValueError("Cet arrêt est introuvable ou déjà clos.")
    l = l.iloc[0]
    err = gi.controler_remise(l["debut"], fin, gc.maintenant())
    if err:
        raise ValueError("\n".join(err))
    _clore_arret(ident, fin)
    if etat_apres:
        enregistrer_etat(l["site"], etat_apres, None, pd.Timestamp(fin).normalize(), f"Remise en marche — arrêt {ident}",
                         gc.maintenant(), synchroniser_arret=False)


def a_l_arret_sans_episode(sites: pd.DataFrame) -> set:
    """Centrales déclarées « À l'arrêt » sans arrêt en cours saisi : indisponibles sur toute la période."""
    ep = arrets_declares()
    return set(sites.loc[sites["etat"] == gi.ARRET, "cle_site"]) - set(ep.loc[ep["fin"].isna(), "cle_site"])


# ============================================================================= lot 4 : visites, équipes, missions
REGISTRE_VISITES, REGISTRE_EQUIPES = "gmao_visites", "gmao_equipes"


def _registre(nom: str, colonnes: list[str], dates: tuple = ()) -> pd.DataFrame:
    from .storage import session_ou_stockage
    d = session_ou_stockage(nom, lambda: pd.DataFrame(columns=colonnes))
    d = pd.DataFrame(columns=colonnes) if d is None or len(d) == 0 else d.copy()
    for c in colonnes:
        if c not in d.columns:
            d[c] = None
    for c in dates:
        d[c] = pd.to_datetime(d[c], errors="coerce")
    return d[colonnes]


def visites_saisies() -> pd.DataFrame:
    """Visites enregistrées dans l'application (registre distinct des inspections importées, que tout réimport
    d'un journal remplace par année)."""
    return _registre(REGISTRE_VISITES, gi.COLONNES_VISITES, ("date", "horodatage"))


def enregistrer_visite(v: dict, aujourd_hui: pd.Timestamp, etat_actuel: str | None = None, appliquer_etat: bool = False) -> str:
    """Enregistre une visite de site. Si `appliquer_etat`, l'état constaté devient l'état de la centrale."""
    from .storage import mettre_a_jour
    err = gi.controler_visite(v.get("site"), v.get("date"), v.get("chef"), v.get("type"), aujourd_hui)
    etat = None if gi.est_vide(v.get("etat_constate")) else v["etat_constate"]
    appliquer = appliquer_etat and etat is not None and etat != etat_actuel
    cause = None if gi.est_vide(v.get("observations")) else str(v["observations"]).strip()[:200]
    if appliquer and not err:
        err += gi.controler_etat(v["site"], etat, v["date"], aujourd_hui, cause or "Constaté en visite")
    if err:
        raise ValueError("\n".join(err))
    d = visites_saisies()
    an = gc.maintenant().year
    nums = d["id"].dropna().astype(str)
    nums = nums[nums.str.startswith(f"VI-{an}-")].str.split("-").str[-1].astype(int)
    ident = f"VI-{an}-{(nums.max() + 1 if len(nums) else 1):04d}"
    corr = correspondances_noms()
    ligne = {"id": ident, "cle_site": g.cle(v["site"]), "site": str(v["site"]).strip(), "date": pd.Timestamp(v["date"]).normalize(),
             "chef": gi.nom_retenu(v["chef"], corr), "membres": ", ".join(gi.liste_membres(v.get("membres"))) or None,
             "equipe": None if gi.est_vide(v.get("equipe")) else str(v["equipe"]).strip(), "type": v["type"], "etat_constate": etat,
             "observations": None if gi.est_vide(v.get("observations")) else str(v["observations"]).strip(),
             "source": "Visite saisie", "auteur": _auteur(), "horodatage": pd.Timestamp(gc.maintenant())}
    mettre_a_jour(REGISTRE_VISITES, pd.concat([d, pd.DataFrame([ligne])], ignore_index=True),
                  f"visite {ident} — {ligne['site']} le {ligne['date']:%d/%m/%Y} ({ligne['type']})")
    if appliquer:
        enregistrer_etat(v["site"], etat, cause or "Constaté en visite", ligne["date"], f"Visite {ident}", aujourd_hui)
    return ident


def equipes() -> pd.DataFrame:
    d = _registre(REGISTRE_EQUIPES, gi.COLONNES_EQUIPES)
    d["statut"] = d["statut"].fillna("Active")
    return d


def enregistrer_equipe(v: dict, ancien_nom: str | None = None) -> None:
    """Crée une équipe de maintenance, ou modifie celle nommée `ancien_nom`."""
    from .storage import mettre_a_jour
    d = equipes()
    autres = set(d.loc[d["nom"] != ancien_nom, "nom"]) if ancien_nom else set(d["nom"])
    err = gi.controler_equipe(v, autres)
    if ancien_nom and ancien_nom not in set(d["nom"]):
        err.append("Équipe à modifier introuvable.")
    if err:
        raise ValueError("\n".join(err))
    ligne = {"nom": " ".join(str(v["nom"]).split()), "zone": str(v["zone"]).strip(), "chef": gi.nom_retenu(v["chef"], correspondances_noms()),
             "telephone": None if gi.est_vide(v.get("telephone")) else str(v["telephone"]).strip(), "statut": v["statut"],
             "membres": ", ".join(gi.liste_membres(v.get("membres"))) or None}
    if ancien_nom:
        i = d.index[d["nom"] == ancien_nom][0]
        for k, x in ligne.items():
            d.loc[i, k] = x
        detail = f"équipe « {ancien_nom} » modifiée"
        if ligne["nom"] != ancien_nom:   # les bons d'intervention suivent le nouveau nom de l'équipe
            bi = gc.table("gmao_bi")
            if (bi["equipe"] == ancien_nom).any():
                bi.loc[bi["equipe"] == ancien_nom, "equipe"] = ligne["nom"]
                gc.sauver("gmao_bi", bi, f"équipe « {ancien_nom} » renommée « {ligne['nom']} »")
    else:
        d = pd.concat([d, pd.DataFrame([ligne])], ignore_index=True)
        detail = f"équipe « {ligne['nom']} » créée ({ligne['zone']}, chef : {ligne['chef']})"
    mettre_a_jour(REGISTRE_EQUIPES, d, detail)


def programmer_mission(site: dict, date_prevue, equipe: str, type_mission: str, consignes: str | None,
                       aujourd_hui: pd.Timestamp) -> str:
    """Programme une mission : un bon d'intervention planifié, affecté à l'équipe (visible dans le planning du GMAO).
    `site` : {"site", "site_id", "phase", "region"}."""
    eq = equipes()
    err = []
    if not site or gi.est_vide(site.get("site")):
        err.append("Choisis la centrale.")
    if date_prevue is None or pd.isna(date_prevue):
        err.append("Renseigne la date prévue.")
    elif pd.Timestamp(date_prevue).normalize() < pd.Timestamp(aujourd_hui).normalize():
        err.append("La date prévue d'une mission ne peut pas être passée.")
    if equipe not in set(eq.loc[eq["statut"] == "Active", "nom"]):
        err.append("Choisis une équipe active.")
    if type_mission not in gi.TYPES_MISSION:
        err.append("Choisis le type de mission.")
    if err:
        raise ValueError("\n".join(err))
    chef = eq.loc[eq["nom"] == equipe, "chef"].iloc[0]
    ligne = {"origine": "Mission programmée", "type": gi.TYPES_MISSION[type_mission],
             "priorite": "Majeure" if type_mission == "Maintenance corrective" else "Mineure",
             "site_id": site.get("site_id"), "site": site["site"], "phase": site.get("phase"), "region": site.get("region"),
             "description": type_mission if gi.est_vide(consignes) else str(consignes).strip(), "statut": "Planifié",
             "centrale_arret": False, "date_creation": pd.Timestamp(aujourd_hui).normalize(),
             "date_prevue": pd.Timestamp(date_prevue).normalize(), "equipe": equipe, "chef": chef}
    return gc.ajouter("gmao_bi", [ligne], "BI", f"mission programmée — {site['site']} le {ligne['date_prevue']:%d/%m/%Y} ({equipe})")[0]


# ============================================================================= lot 5 : stocks
def magasins() -> list[str]:
    """Magasins configurés (paramètre de l'application) ; à défaut, la liste d'origine du GMAO."""
    m = valeur(PAGE, "magasins", None)
    return [str(x) for x in m] if isinstance(m, list) and m else list(gc.MAGASINS)


def stocks() -> pd.DataFrame:
    return gi.stocks_par_magasin(gc.table("gmao_mouvements"))


def ajouter_magasin(nom: str) -> None:
    propre = " ".join(str(nom or "").split())
    actuels = magasins()
    if not propre:
        raise ValueError("Renseigne le nom du nouveau magasin.")
    if gi.cle_nom(propre) in {gi.cle_nom(m) for m in actuels}:
        raise ValueError("Ce magasin existe déjà.")
    enregistrer_reglages({"magasins": actuels + [propre]})


def retirer_magasin(nom: str) -> None:
    """Retire un magasin de la liste, seulement s'il ne contient plus aucun stock (rien ne disparaît en silence)."""
    actuels = magasins()
    if nom not in actuels:
        raise ValueError("Magasin introuvable.")
    if len(actuels) == 1:
        raise ValueError("Il faut garder au moins un magasin.")
    s = stocks()
    reste = s[(s["magasin"] == nom) & (s["stock"].abs() > 1e-9)]
    if len(reste):
        raise ValueError(f"Le magasin « {nom} » contient encore {len(reste)} article(s) en stock : fais un inventaire à zéro "
                         "ou transfère-les (sortie puis entrée) avant de le retirer.")
    enregistrer_reglages({"magasins": [m for m in actuels if m != nom]})


def enregistrer_mouvement(v: dict) -> str:
    """Enregistre un mouvement de stock : entrée, sortie (vers un site) ou inventaire (quantité comptée).
    `v` : code, type, quantite, date, magasin, site, reference, saisi_par."""
    maintenant = pd.Timestamp(gc.maintenant())
    s = stocks()
    dispo = s.loc[(s["code"] == v.get("code")) & (s["magasin"] == v.get("magasin")), "stock"].sum()
    err = gi.controler_mouvement(v, maintenant, dispo)
    if v.get("code") and v["code"] not in set(gc.table("gmao_articles")["code"]):
        err.append("Article inconnu du catalogue.")
    if v.get("magasin") and v["magasin"] not in magasins():
        err.append("Magasin inconnu : ajoute-le d'abord à la liste des magasins.")
    if err:
        raise ValueError("\n".join(err))
    d = pd.Timestamp(v["date"])
    if d.normalize() == maintenant.normalize():
        d = maintenant                              # mouvement du jour : horodaté à l'instant de la saisie
    ligne = {"date": d, "code": v["code"], "type": v["type"], "quantite": float(v["quantite"]), "magasin": v["magasin"],
             "site_destinataire": None if gi.est_vide(v.get("site")) else str(v["site"]).strip(),
             "reference": None if gi.est_vide(v.get("reference")) else str(v["reference"]).strip(),
             "motif": None if gi.est_vide(v.get("reference")) else str(v["reference"]).strip(),
             "auteur": " ".join(str(v["saisi_par"]).split())}
    detail = (f"inventaire {v['code']} au {d:%d/%m/%Y} : {ligne['quantite']:g} compté(s) ({v['magasin']})" if v["type"] == "Inventaire"
              else f"{v['type'].lower()} de stock {v['code']} × {ligne['quantite']:g} ({v['magasin']})"
              + (f" vers {ligne['site_destinataire']}" if ligne["site_destinataire"] else ""))
    return gc.ajouter("gmao_mouvements", [ligne], "MV", detail)[0]


def creer_article(v: dict) -> str:
    """Article hors catalogue : code, désignation, catégorie, unité, seuil minimum, prix unitaire."""
    art = gc.table("gmao_articles")
    err = gi.controler_article(v, set(art["code"].dropna()))
    if err:
        raise ValueError("\n".join(err))
    code = str(v["code"]).strip().upper()
    ligne = {"code": code, "designation": " ".join(str(v["designation"]).split()), "categorie": v.get("categorie"),
             "systeme": gc.CATEGORIE_VERS_SYSTEME.get(v.get("categorie")), "unite": v.get("unite") or "u",
             "magasin": magasins()[0], "stock_mini": float(v.get("stock_mini") or 0),
             "prix_unitaire": float(v.get("prix_unitaire") or 0)}
    gc.ajouter("gmao_articles", [ligne], None, f"article hors catalogue créé : {code} — {ligne['designation']}")
    return code


def parametrer_article(code: str, stock_mini, prix_unitaire) -> None:
    for x, lib in ((stock_mini, "Le seuil minimum"), (prix_unitaire, "Le prix unitaire")):
        if x is not None and not pd.isna(x) and x < 0:
            raise ValueError(f"{lib} ne peut pas être négatif.")
    art = gc.table("gmao_articles")
    if code not in set(art["code"]):
        raise ValueError("Article introuvable.")
    gc.modifier("gmao_articles", code, {"stock_mini": float(stock_mini or 0), "prix_unitaire": float(prix_unitaire or 0)},
                f"article {code} : seuil {float(stock_mini or 0):g}, prix {float(prix_unitaire or 0):g} FCFA", cle="code")
