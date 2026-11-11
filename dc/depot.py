"""Accès aux données du module Data Center : création des tables, contenu initial, lectures, écritures
et journal d'audit. Toute écriture passe par ce module et laisse une trace dans dc_audit."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import delete, insert, select, update

from . import modele as m
from . import referentiel as ref
from .regles import Seuil, evaluer_releve

TZ = ZoneInfo("Africa/Douala")
MOTEUR = None  # remplaçable dans les tests (moteur SQLite en mémoire)


def maintenant() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None, microsecond=0)


def moteur():
    if MOTEUR is not None:
        return MOTEUR
    from utils.storage import _eng
    return _eng()


def _utilisateur() -> tuple[str, str]:
    try:
        from utils.auth import utilisateur
        u = utilisateur() or {}
        return u.get("login", "?"), u.get("role", "")
    except Exception:  # noqa: BLE001
        return "?", ""


def tracer(cx, action: str, objet: str, objet_id=None, detail=None) -> None:
    login, role = _utilisateur()
    cx.execute(insert(m.audit).values(horodatage=maintenant(), utilisateur=login, role=role, action=action,
                                      objet=objet, objet_id=None if objet_id is None else str(objet_id),
                                      detail=json.dumps(detail, ensure_ascii=False, default=str) if detail else None))


# ----------------------------------------------------------------------------- initialisation
_INIT_FAIT: set = set()


def initialiser() -> dict:
    """Crée les tables manquantes et charge le contenu initial s'il est absent (idempotent)."""
    eng = moteur()
    cle = str(eng.url)
    if cle in _INIT_FAIT:
        return {}
    m.meta.create_all(eng)
    bilan = {}
    with eng.begin() as cx:
        if not cx.execute(select(m.salle.c.id).limit(1)).first():
            for s in ref.SALLES:
                cx.execute(insert(m.salle).values(**s))
            bilan["salles"] = len(ref.SALLES)
        salles = dict(cx.execute(select(m.salle.c.nom, m.salle.c.id)).all())
        codes = {r[0] for r in cx.execute(select(m.equipement.c.code)).all()}
        nouveaux = [e for e in ref.EQUIPEMENTS if e["code"] not in codes]
        for e in nouveaux:
            v = {k: e.get(k) for k in m.equipement.c.keys() if k in e}
            v["salle_id"] = salles.get(e.get("salle"))
            cx.execute(insert(m.equipement).values(**v))
        if nouveaux:
            bilan["equipements"] = len(nouveaux)
        if not cx.execute(select(m.seuil.c.grandeur).limit(1)).first():
            for s in ref.SEUILS:
                cx.execute(insert(m.seuil).values(**s.__dict__))
            bilan["seuils"] = len(ref.SEUILS)
        if not cx.execute(select(m.modele_controle.c.id).limit(1)).first():
            ctl = ref.controles()
            for c in ctl:
                cx.execute(insert(m.modele_controle).values(
                    cible=c["cible"], phase=c["phase"], point=c["point"], commande=c["commande"], normal=c["normal"],
                    a_signaler=c["a_signaler"], frequence=c["frequence"], grandeur=c["grandeur"], source=c["source"],
                    actif=True))
            bilan["controles"] = len(ctl)
        if bilan:
            tracer(cx, "initialisation", "module", detail=bilan)
    _INIT_FAIT.add(cle)
    return bilan


# ----------------------------------------------------------------------------- lectures
def _df(stmt) -> pd.DataFrame:
    with moteur().connect() as cx:
        r = cx.execute(stmt)
        return pd.DataFrame(r.fetchall(), columns=list(r.keys()))


def salles() -> pd.DataFrame:
    return _df(select(m.salle))


def baies() -> pd.DataFrame:
    return _df(select(m.baie))


def equipements() -> pd.DataFrame:
    e = _df(select(m.equipement))
    s = salles().set_index("id")["nom"] if len(salles()) else pd.Series(dtype=str)
    b = baies().set_index("id")["nom"] if len(baies()) else pd.Series(dtype=str)
    e["salle"] = e["salle_id"].map(s)
    e["baie"] = e["baie_id"].map(b)
    return e


def seuils() -> dict[str, Seuil]:
    d = _df(select(m.seuil))
    return {r["grandeur"]: Seuil(**{k: (None if pd.isna(v) else v) for k, v in r.items()}) for _, r in d.iterrows()}


def seuils_df() -> pd.DataFrame:
    return _df(select(m.seuil))


def controles(actifs_seulement: bool = True) -> pd.DataFrame:
    st_ = select(m.modele_controle)
    if actifs_seulement:
        st_ = st_.where(m.modele_controle.c.actif.is_(True))
    return _df(st_)


def controles_pour(eq: pd.Series, ctl: pd.DataFrame | None = None) -> pd.DataFrame:
    """Contrôles applicables à un équipement : ceux qui le visent par son code, ou par son type de contrôle."""
    ctl = controles() if ctl is None else ctl
    cibles = {eq["code"]} | ({eq["type_controle"]} if eq.get("type_controle") else set())
    return ctl[ctl["cible"].isin(cibles)]


def inspections() -> pd.DataFrame:
    return _df(select(m.inspection))


def releves() -> pd.DataFrame:
    """Relevés enrichis de l'inspection (date, équipement) et du contrôle (point, fréquence)."""
    stmt = (select(m.releve.c.id, m.releve.c.inspection_id, m.releve.c.controle_id, m.releve.c.statut,
                   m.releve.c.valeur, m.releve.c.severite, m.releve.c.commentaire, m.releve.c.photo_nom,
                   m.inspection.c.date, m.inspection.c.equipement_id, m.inspection.c.inspecteur,
                   m.modele_controle.c.point, m.modele_controle.c.phase, m.modele_controle.c.frequence,
                   m.modele_controle.c.grandeur)
            .join(m.inspection, m.releve.c.inspection_id == m.inspection.c.id)
            .join(m.modele_controle, m.releve.c.controle_id == m.modele_controle.c.id))
    return _df(stmt)


def photo(releve_id: int) -> tuple[str, str] | None:
    with moteur().connect() as cx:
        r = cx.execute(select(m.releve.c.photo_nom, m.releve.c.photo_b64).where(m.releve.c.id == releve_id)).first()
    return (r[0], r[1]) if r and r[1] else None


def constats() -> pd.DataFrame:
    return _df(select(m.constat))


def reseau_ip() -> pd.DataFrame:
    return _df(select(m.reseau_ip))


def journal_audit(limite: int = 500) -> pd.DataFrame:
    return _df(select(m.audit).order_by(m.audit.c.id.desc()).limit(limite))


# ----------------------------------------------------------------------------- écritures
def enregistrer_inspection(equipement_id: int, inspecteur: str, frequence: str | None, saisies: list[dict],
                           observations: str = "", date: datetime | None = None) -> tuple[int, dict]:
    """Enregistre une inspection et ses relevés. Chaque saisie : controle_id, statut, valeur, commentaire,
    photo_nom, photo_b64. La sévérité de chaque relevé est calculée ici (jamais saisie)."""
    date = date or maintenant()
    sl = seuils()
    with moteur().begin() as cx:
        crit = cx.execute(select(m.equipement.c.criticite, m.equipement.c.code)
                          .where(m.equipement.c.id == equipement_id)).first()
        gr = dict(cx.execute(select(m.modele_controle.c.id, m.modele_controle.c.grandeur)).all())
        lignes = []
        for s in saisies:
            g = gr.get(s["controle_id"])
            sev = evaluer_releve(s.get("statut"), s.get("valeur"), sl.get(g) if g else None, crit[0] if crit else "Moyenne")
            lignes.append({**s, "severite": sev})
        empreinte = hashlib.sha256(json.dumps(
            {"inspecteur": inspecteur, "date": date.isoformat(), "equipement": equipement_id,
             "releves": [(l["controle_id"], l.get("statut"), l.get("valeur")) for l in lignes]},
            ensure_ascii=False, default=str).encode()).hexdigest()
        login, _ = _utilisateur()
        iid = cx.execute(insert(m.inspection).values(date=date, equipement_id=equipement_id, frequence=frequence,
                                                     inspecteur=inspecteur, signature=empreinte,
                                                     observations=observations or None, auteur=login)
                         ).inserted_primary_key[0]
        for l in lignes:
            cx.execute(insert(m.releve).values(inspection_id=iid, controle_id=l["controle_id"], statut=l.get("statut"),
                                               valeur=l.get("valeur"), severite=l["severite"],
                                               commentaire=l.get("commentaire") or None, photo_nom=l.get("photo_nom"),
                                               photo_b64=l.get("photo_b64")))
        bilan = {k: sum(1 for l in lignes if l["severite"] == k) for k in ("OK", "Avertissement", "Critique")}
        tracer(cx, "inspection", "equipement", crit[1] if crit else equipement_id, {"inspection": iid, **bilan})
    return iid, bilan


def modifier_equipements(avant: pd.DataFrame, apres: pd.DataFrame) -> int:
    """Applique les modifications du registre (comparaison ligne à ligne) ; ajoute les nouvelles lignes."""
    cols = [c for c in m.equipement.c.keys() if c != "id" and c in apres.columns]
    nb = 0
    with moteur().begin() as cx:
        index_avant = avant.set_index("id") if len(avant) else pd.DataFrame()
        for _, r in apres.iterrows():
            v = {c: (None if (not isinstance(r[c], (list, dict)) and pd.isna(r[c])) else r[c]) for c in cols}
            for c in ("date_mes", "fin_garantie"):
                if v.get(c) is not None:
                    v[c] = pd.Timestamp(v[c]).to_pydatetime()
            if pd.isna(r.get("id")):
                if not v.get("code") or not v.get("designation") or not v.get("systeme"):
                    continue
                nid = cx.execute(insert(m.equipement).values(**v)).inserted_primary_key[0]
                tracer(cx, "création", "equipement", v["code"], v)
                nb += 1
            else:
                ident = int(r["id"])
                anc = index_avant.loc[ident] if ident in index_avant.index else None
                diff = {c: (None if anc is None else anc.get(c), v[c]) for c in cols
                        if anc is None or str(anc.get(c)) != str(v[c]) and not (pd.isna(anc.get(c)) and v[c] is None)}
                if diff:
                    cx.execute(update(m.equipement).where(m.equipement.c.id == ident).values(**{c: v[c] for c in diff}))
                    tracer(cx, "modification", "equipement", v.get("code") or ident,
                           {c: {"avant": a, "après": b} for c, (a, b) in diff.items()})
                    nb += 1
    return nb


def modifier_seuils(df: pd.DataFrame) -> None:
    with moteur().begin() as cx:
        for _, r in df.iterrows():
            v = {c: (None if pd.isna(r[c]) else float(r[c])) for c in ("avert_min", "avert_max", "crit_min", "crit_max")}
            cx.execute(update(m.seuil).where(m.seuil.c.grandeur == r["grandeur"]).values(**v))
        tracer(cx, "modification", "seuils", detail=df.to_dict("records"))


def modifier_controles(df: pd.DataFrame) -> None:
    with moteur().begin() as cx:
        for _, r in df.iterrows():
            cx.execute(update(m.modele_controle).where(m.modele_controle.c.id == int(r["id"]))
                       .values(frequence=r["frequence"], actif=bool(r["actif"])))
        tracer(cx, "modification", "listes de contrôle", detail={"lignes": len(df)})


def remplacer_donnees_sensibles(ip: pd.DataFrame, cst: pd.DataFrame, source: str) -> dict:
    """Remplace le plan d'adressage ; ajoute les constats nouveaux (un constat déjà suivi garde son statut)."""
    with moteur().begin() as cx:
        cx.execute(delete(m.reseau_ip))
        for r in ip.to_dict("records"):
            cx.execute(insert(m.reseau_ip).values(**r))
        deja = {r[0] for r in cx.execute(select(m.constat.c.constat)).all()}
        nv = [r for r in cst.to_dict("records") if r["constat"] not in deja]
        for r in nv:
            cx.execute(insert(m.constat).values(**r, statut="Ouvert", source=source))
        tracer(cx, "import", "cartographie", detail={"plages_ip": len(ip), "constats_ajoutes": len(nv), "source": source})
    return {"plages_ip": len(ip), "constats_ajoutes": len(nv)}


def modifier_constats(df: pd.DataFrame) -> None:
    with moteur().begin() as cx:
        for _, r in df.iterrows():
            ech = r.get("echeance")
            cx.execute(update(m.constat).where(m.constat.c.id == int(r["id"])).values(
                statut=r["statut"], action=None if pd.isna(r.get("action")) else r["action"],
                responsable=None if pd.isna(r.get("responsable")) else r["responsable"],
                echeance=None if ech is None or pd.isna(ech) else pd.Timestamp(ech).to_pydatetime()))
        tracer(cx, "modification", "constats", detail={"lignes": len(df)})
