"""
Stockage durable des registres saisis dans l'application.

Moteur :
  - PostgreSQL (ou toute base SQLAlchemy) si l'adresse est déclarée dans les
    secrets :   [database]  url = "postgresql+psycopg2://user:mdp@hote:5432/aer"
    → recommandé : base hébergée sur le Data Center de l'AER ;
  - sinon, fichier SQLite local `data/aer_registres.sqlite`.
    En local ou sur un serveur de l'AER, ce fichier est durable. Sur Streamlit
    Community Cloud, il est EFFACÉ à chaque redémarrage de l'application :
    la page Administration le signale et propose la sauvegarde complète.

Chaque registre (DataFrame) est stocké sous un nom (ex. « vehicules_register »)
au format JSON « table » de pandas, qui conserve les types (dates, nombres).
Le journal des actions est une table à part.

La sauvegarde / restauration complète (un classeur Excel, une feuille par
registre + le journal) fonctionne quel que soit le moteur.
"""
from __future__ import annotations

import io
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

SQLITE_PATH = Path(__file__).resolve().parent.parent / "data" / "aer_registres.sqlite"

# Registres gérés : nom technique → libellé
REGISTRES = {
    "vehicules_register": "Parc automobile — véhicules",
    "vehicules_journal": "Parc automobile — journal d'utilisation",
    "projets_register": "Suivi de projets",
    "revolving_register": "Fonds revolving",
    "personnel_equipes": "Personnel — équipes (après mouvements)",
    "personnel_unassigned": "Personnel — non affecté (après mouvements)",
    "personnel_mouvements": "Personnel — mouvements",
    "personnel_signature": "Personnel — empreinte du classeur source",
    "paie_registre": "Masse salariale — registre de paie",
    "recr_profils": "Masse salariale — profils de recrutement",
    "budget_register": "Suivi budgétaire",
    "supervision_mesures": "Supervision des centrales — mesures importées",
    "ventes_register": "Recettes — ventes importées",
    "plaidoyer_textes": "Dossier de plaidoyer — textes",
    "plaidoyer_references": "Dossier de plaidoyer — références validées",
    "recharges_datacenter": "Recharges Data Center — données mensuelles",
    "classeur_principal": "Classeur de données principal (parc solaire, équipes)",
    "compteurs_lots": "Statistiques compteurs — lots Holley déposés",
    "parametres_pages": "Réglages des pages (seuils, phases, objectifs, options, corrections)",
    "maintenance_interventions": "Parc solaire — maintenance (arrêts, dépannages, visites)",
    "gmao_defauts": "GMAO — journal des défauts (journaux de maintenance)",
    "gmao_statuts": "GMAO — état de fonctionnement des centrales",
    "gmao_inspections": "GMAO — inspections",
    "gmao_affectations": "GMAO — affectation site / zone / responsable",
    "gmao_di": "GMAO — demandes d'intervention (DI)",
    "gmao_bi": "GMAO — bons d'intervention (BI)",
    "gmao_plans": "GMAO — gammes de maintenance préventive",
    "gmao_articles": "GMAO — catalogue des articles / pièces",
    "gmao_mouvements": "GMAO — mouvements de stock",
    "gmao_achats": "GMAO — demandes et commandes d'achat",
    "gmao_budget": "GMAO — budget de maintenance",
    "gmao_prestataires": "GMAO — prestataires",
    "gmao_equipements": "GMAO — équipements par centrale",
}


_RACINE = Path(__file__).resolve().parent.parent


def _normaliser_url(url: str) -> str:
    """Neon (et la plupart des hébergeurs) fournissent « postgres://… » ou « postgresql://… » :
    SQLAlchemy a besoin du pilote explicite « postgresql+psycopg2:// ». Le reste (dont
    ?sslmode=require&channel_binding=require) est conservé tel quel."""
    url = url.strip().strip('"').strip("'")
    for prefixe in ("postgres://", "postgresql://"):
        if url.startswith(prefixe):
            return "postgresql+psycopg2://" + url[len(prefixe):]
    return url


def _depuis_fichier_env(cle: str) -> str | None:
    """Lit une variable dans .env.local puis .env à la racine du projet (fichiers écrits par
    `neon env pull` / `neon deploy`, ignorés par git) — utile en exécution locale."""
    for nom in (".env.local", ".env"):
        f = _RACINE / nom
        if f.exists():
            for ligne in f.read_text(encoding="utf-8").splitlines():
                ligne = ligne.strip()
                if ligne.startswith("export "):
                    ligne = ligne[7:]
                if ligne.startswith(cle + "="):
                    return ligne.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _url() -> str:
    """Adresse de la base, par ordre de priorité :
    1. secrets Streamlit  [database] url = "…"  ;
    2. variable DATABASE_URL (secret Streamlit de premier niveau, variable d'environnement,
       ou fichier .env.local / .env écrit par le CLI Neon) — chaîne « pooled » de Neon ;
    3. à défaut, fichier SQLite local."""
    import os
    try:
        return _normaliser_url(str(st.secrets["database"]["url"]))
    except Exception:  # noqa: BLE001
        pass
    url = os.environ.get("DATABASE_URL")
    if not url:
        try:
            url = str(st.secrets["DATABASE_URL"])
        except Exception:  # noqa: BLE001
            url = None
    url = url or _depuis_fichier_env("DATABASE_URL")
    if url:
        return _normaliser_url(url)
    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{SQLITE_PATH}"


def moteur_description() -> str:
    u = _url()
    if u.startswith("sqlite"):
        return "SQLite local (data/aer_registres.sqlite)"
    return "Base de données externe (" + u.split("://", 1)[0].split("+")[0] + ")"


def moteur_ephemere() -> bool:
    """Vrai sur Streamlit Community Cloud sans base externe (fichiers effacés au redémarrage)."""
    import os
    return _url().startswith("sqlite") and (os.environ.get("HOSTNAME", "").startswith("streamlit")
                                            or Path("/mount/src").exists())


@st.cache_resource(show_spinner=False)
def _engine(url: str):
    from sqlalchemy import create_engine, text
    eng = create_engine(url, pool_pre_ping=True, pool_recycle=300)
    with eng.begin() as cx:
        cx.execute(text("CREATE TABLE IF NOT EXISTS aer_registres (nom VARCHAR(80) PRIMARY KEY, "
                        "contenu TEXT NOT NULL, maj VARCHAR(32), auteur VARCHAR(80))"))
        cx.execute(text("CREATE TABLE IF NOT EXISTS aer_journal (horodatage VARCHAR(32), utilisateur VARCHAR(80), "
                        "role VARCHAR(20), action VARCHAR(120), detail TEXT)"))
    return eng


def _eng():
    return _engine(_url())


def _vers_json(df: pd.DataFrame) -> str:
    d = df.copy()
    d.columns = [str(c) for c in d.columns]
    d = d.reset_index(drop=True)
    return d.to_json(orient="table", index=False, date_format="iso", force_ascii=False)


def _depuis_json(s: str) -> pd.DataFrame:
    return pd.read_json(io.StringIO(s), orient="table")


def charger(nom: str) -> pd.DataFrame | None:
    """Renvoie le registre enregistré, ou None s'il n'existe pas (ou si la base est injoignable)."""
    try:
        from sqlalchemy import text
        with _eng().connect() as cx:
            row = cx.execute(text("SELECT contenu FROM aer_registres WHERE nom = :n"), {"n": nom}).fetchone()
        return _depuis_json(row[0]) if row else None
    except Exception as exc:  # noqa: BLE001
        st.session_state["storage_erreur"] = f"Lecture de « {nom} » impossible : {exc}"
        return None


def enregistrer(nom: str, df: pd.DataFrame, detail: str = "") -> bool:
    """Enregistre le registre et trace l'action dans le journal. Renvoie False en cas d'échec."""
    from .auth import utilisateur
    u = utilisateur() or {}
    try:
        from sqlalchemy import text
        maj = datetime.now().isoformat(timespec="seconds")
        with _eng().begin() as cx:
            cx.execute(text("DELETE FROM aer_registres WHERE nom = :n"), {"n": nom})
            cx.execute(text("INSERT INTO aer_registres (nom, contenu, maj, auteur) VALUES (:n, :c, :m, :a)"),
                       {"n": nom, "c": _vers_json(df), "m": maj, "a": u.get("login", "?")})
        ecrire_journal(u.get("login", "?"), u.get("role", ""), f"Enregistrement — {REGISTRES.get(nom, nom)}",
                       detail or f"{len(df)} ligne(s)")
        st.session_state.pop("storage_erreur", None)
        return True
    except Exception as exc:  # noqa: BLE001
        st.session_state["storage_erreur"] = f"Enregistrement de « {nom} » impossible : {exc}"
        return False


def etat_registres() -> pd.DataFrame:
    try:
        from sqlalchemy import text
        with _eng().connect() as cx:
            rows = cx.execute(text("SELECT nom, maj, auteur, LENGTH(contenu) FROM aer_registres")).fetchall()
    except Exception:  # noqa: BLE001
        rows = []
    connus = {r[0]: r for r in rows}
    lignes = []
    for nom, lib in REGISTRES.items():
        r = connus.get(nom)
        lignes.append({"Registre": lib, "Nom technique": nom, "Dernière mise à jour": r[1] if r else "—",
                       "Par": r[2] if r else "—", "Taille (Ko)": round(r[3] / 1024, 1) if r else 0})
    return pd.DataFrame(lignes)


# ------------------------------------------------------------------ journal
def ecrire_journal(login: str, role: str, action: str, detail: str = "") -> None:
    try:
        from sqlalchemy import text
        with _eng().begin() as cx:
            cx.execute(text("INSERT INTO aer_journal VALUES (:h, :u, :r, :a, :d)"),
                       {"h": datetime.now().isoformat(timespec="seconds"), "u": login, "r": role,
                        "a": action[:120], "d": (detail or "")[:2000]})
    except Exception:  # noqa: BLE001
        pass


def lire_journal(limite: int = 2000) -> pd.DataFrame:
    try:
        from sqlalchemy import text
        with _eng().connect() as cx:
            rows = cx.execute(text("SELECT horodatage, utilisateur, role, action, detail FROM aer_journal "
                                   "ORDER BY horodatage DESC LIMIT :l"), {"l": limite}).fetchall()
        return pd.DataFrame(rows, columns=["Horodatage", "Utilisateur", "Rôle", "Action", "Détail"])
    except Exception:  # noqa: BLE001
        return pd.DataFrame(columns=["Horodatage", "Utilisateur", "Rôle", "Action", "Détail"])


# ------------------------------------------------------------------ sauvegarde complète
def sauvegarde_complete() -> bytes:
    """Classeur Excel : une feuille « _index » + une feuille JSON par registre + le journal."""
    buf = io.BytesIO()
    index = []
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for nom in REGISTRES:
            df = charger(nom)
            if df is None:
                continue
            index.append({"nom": nom, "lignes": len(df)})
            # le JSON conserve les types ; il est découpé en morceaux < 32 000 caractères (limite Excel)
            s = _vers_json(df)
            morceaux = [s[i:i + 30000] for i in range(0, len(s), 30000)] or [""]
            pd.DataFrame({"json": morceaux}).to_excel(xw, sheet_name=nom[:31], index=False)
            lisible = df.drop(columns=["b64"]) if "b64" in df.columns else df  # contenu binaire : déjà dans la feuille JSON
            lisible.to_excel(xw, sheet_name=("v_" + nom)[:31], index=False)  # lecture humaine
        pd.DataFrame(index, columns=["nom", "lignes"]).to_excel(xw, sheet_name="_index", index=False)
        lire_journal(100000).to_excel(xw, sheet_name="_journal", index=False)
    return buf.getvalue()


def restaurer(fichier) -> list[str]:
    """Restaure les registres d'une sauvegarde complète. Renvoie la liste des registres restaurés."""
    xls = pd.ExcelFile(fichier)
    if "_index" not in xls.sheet_names:
        raise ValueError("ce fichier n'est pas une sauvegarde complète de l'application (feuille « _index » absente).")
    idx = pd.read_excel(xls, sheet_name="_index")
    if "nom" not in idx.columns or idx.empty:
        raise ValueError("cette sauvegarde ne contient aucun registre : elle a été faite alors qu'aucune donnée "
                         "n'était enregistrée. Il n'y a rien à restaurer.")
    faits = []
    for nom in idx["nom"].astype(str):
        if nom not in REGISTRES or nom[:31] not in xls.sheet_names:
            continue
        s = "".join(pd.read_excel(xls, sheet_name=nom[:31])["json"].fillna("").astype(str))
        df = _depuis_json(s)
        if enregistrer(nom, df, f"restauration depuis sauvegarde — {len(df)} ligne(s)"):
            st.session_state.pop(nom, None)
            st.session_state.pop(f"_empreinte_{nom}", None)
            faits.append(nom)
    return faits


# ------------------------------------------------------------------ fichiers déposés (contenu binaire)
# Un registre « fichiers » est un DataFrame : une ligne par fichier (nom, contenu en base64, date, auteur).
def charger_fichiers(nom: str) -> list[dict]:
    """Fichiers enregistrés sous `nom` : [{"fichier": str, "contenu": bytes, "maj": str}, …] (liste vide sinon)."""
    import base64
    df = charger(nom)
    if df is None or df.empty or "b64" not in df.columns:
        return []
    return [{"fichier": str(r["fichier"]), "contenu": base64.b64decode(str(r["b64"])), "maj": str(r.get("maj", ""))}
            for _, r in df.iterrows()]


def enregistrer_fichiers(nom: str, fichiers: list[dict], detail: str = "") -> bool:
    """Remplace le registre `nom` par la liste de fichiers donnée ({"fichier", "contenu"[, "maj"]})."""
    import base64
    from .auth import peut_modifier
    if not peut_modifier():
        return False
    maj = datetime.now().isoformat(timespec="seconds")
    df = pd.DataFrame([{"fichier": f["fichier"], "b64": base64.b64encode(f["contenu"]).decode("ascii"),
                        "taille": len(f["contenu"]), "maj": f.get("maj") or maj} for f in fichiers],
                      columns=["fichier", "b64", "taille", "maj"])
    return enregistrer(nom, df, detail or f"{len(fichiers)} fichier(s)")


# ------------------------------------------------------------------ aide aux registres de session
def session_ou_stockage(nom: str, defaut_factory):
    """Renvoie le registre de session ; au premier appel de la session, le recharge depuis le stockage
    durable s'il existe, sinon crée la valeur par défaut."""
    if nom not in st.session_state:
        df = charger(nom)
        st.session_state[nom] = df if df is not None else defaut_factory()
        st.session_state[f"_empreinte_{nom}"] = _empreinte(st.session_state[nom])
    return st.session_state[nom]


def _empreinte(df) -> str:
    import hashlib
    try:
        return hashlib.sha1(_vers_json(df).encode("utf-8")).hexdigest()
    except Exception:  # noqa: BLE001
        return ""


def mettre_a_jour(nom: str, df: pd.DataFrame, detail: str = "") -> bool:
    """Met à jour le registre de session et l'enregistre durablement — uniquement s'il a réellement
    changé (les pages rappellent cette fonction à chaque réexécution) et si le rôle le permet."""
    from .auth import peut_modifier
    e = _empreinte(df)
    if e and st.session_state.get(f"_empreinte_{nom}") == e:
        st.session_state[nom] = df
        return True
    if not peut_modifier():
        st.warning("🔒 Votre profil est en consultation seule : la modification n'a pas été enregistrée.")
        return False
    st.session_state[nom] = df
    ok = enregistrer(nom, df, detail)
    if ok:
        st.session_state[f"_empreinte_{nom}"] = e
    else:
        st.warning("⚠️ Modification appliquée pour cette session, mais non enregistrée durablement : "
                   + st.session_state.get("storage_erreur", ""))
    return ok


def enregistrer_si_change(nom: str, df: pd.DataFrame) -> None:
    """Enregistre durablement la sortie d'un éditeur SANS la réinjecter dans la session
    (évite que Streamlit ré-applique les ajouts de lignes de l'éditeur sur ses propres résultats)."""
    from .auth import peut_modifier
    e = _empreinte(df)
    if not e or st.session_state.get(f"_empreinte_{nom}") == e or not peut_modifier():
        return
    if enregistrer(nom, df):
        st.session_state[f"_empreinte_{nom}"] = e
