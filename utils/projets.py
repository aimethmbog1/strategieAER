"""
Suivi de l'avancement des projets d'électrification — registre à alimenter.

Contrairement à `utils/data.py` (lecture du classeur Excel, qui ne contient
AUCUNE notion d'avancement de projet — seulement une photo de capacité : sites
installés, personnel, puissance), ce module ne connaît aucun statut réel de
projet au départ. Comme pour le Fonds revolving (`utils/revolving.py`), le
registre démarre VIDE et n'est alimenté que par ce que l'utilisateur saisit
ici — rien n'est déduit ni inventé à partir du classeur.

Ce que ce module fournit en plus d'un simple formulaire :
  - le rattachement de chaque ligne à un site RÉEL des 499 sites du parc
    solaire (Région / Antenne / Phase recopiées depuis la feuille « Données
    sites », jamais ressaisies à la main, pour éviter toute incohérence) ;
  - un marqueur « région prioritaire » (NOSO = Nord-Ouest + Sud-Ouest, et
    Extrême-Nord) calculé à partir de la région réelle du site, pour pouvoir
    cibler la relance dans ces zones sans avoir à le ressaisir ;
  - un indicateur « jours depuis le dernier mouvement », qui ne mesure que le
    temps écoulé depuis la dernière mise à jour SAISIE ici — un registre vide
    ou non tenu à jour ne veut pas dire « aucun projet en retard », seulement
    « rien n'a encore été renseigné » (affiché explicitement dans l'UI).
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from .storage import mettre_a_jour, session_ou_stockage

# Régions en crise ciblées par la demande de relance (NOSO = Nord-Ouest +
# Sud-Ouest, + Extrême-Nord). Noms exactement alignés sur la colonne
# « Région » de la feuille « Données sites » du classeur AER.
REGIONS_PRIORITAIRES = ["Nord-Ouest", "Sud-Ouest", "Extrême-Nord"]

STATUTS_PROJET = ["Planifié", "En cours", "Suspendu", "Repris", "Terminé"]
STATUTS_A_RELANCER = ["Planifié", "Suspendu"]  # statuts qui justifient une action de reprise/relance

MOTIF_NON_RENSEIGNE = "(non renseigné)"
MOTIFS_BLOCAGE_SUGGERES = [
    "Sécurité / accès zone à risque",
    "Financement en attente",
    "Logistique / approvisionnement matériel",
    "Litige foncier ou communautaire",
    "Personnel insuffisant sur zone",
    "Attente de validation administrative",
    "Autre (préciser en note)",
]
# Une chaîne vide "" comme option de SelectboxColumn Streamlit s'affiche comme
# "None" dans le tableau (bug d'affichage constaté) — on utilise ce libellé
# explicite comme valeur par défaut partout où un motif n'est pas renseigné.
MOTIFS_BLOCAGE_OPTIONS = [MOTIF_NON_RENSEIGNE] + MOTIFS_BLOCAGE_SUGGERES

REGISTER_COLUMNS = [
    "N° projet",
    "Site",
    "Région",
    "Antenne proposée",
    "Phase",
    "Statut",
    "Date de dernier mouvement",
    "Motif de blocage",
    "Responsable désigné",
    "Notes",
]


def empty_register() -> pd.DataFrame:
    df = pd.DataFrame(columns=REGISTER_COLUMNS)
    df["Date de dernier mouvement"] = pd.to_datetime(df["Date de dernier mouvement"])
    return df


def get_register() -> pd.DataFrame:
    # registre durable : rechargé depuis le stockage (utils/storage.py) au début de chaque session
    return session_ou_stockage("projets_register", empty_register)


def set_register(df: pd.DataFrame) -> None:
    mettre_a_jour("projets_register", df)


def next_projet_id(df: pd.DataFrame) -> str:
    n = len(df) + 1
    annee = date.today().strftime("%Y")
    return f"PRJ-{annee}-{n:04d}"


def site_lookup(sites: pd.DataFrame) -> pd.DataFrame:
    """Table Site -> Région / Antenne proposée / Phase, à partir des 499 sites
    réels — c'est la SEULE source utilisée pour rattacher une ligne du
    registre à une région/antenne/phase, jamais une saisie libre."""
    if sites is None or sites.empty:
        return pd.DataFrame(columns=["Nom du site", "Région", "Antenne proposée", "Phase"])
    cols = [c for c in ["Nom du site", "Région", "Antenne proposée", "Phase"] if c in sites.columns]
    return sites[cols].drop_duplicates(subset=["Nom du site"]).sort_values("Nom du site")


def is_region_prioritaire(region: str) -> bool:
    return str(region).strip() in REGIONS_PRIORITAIRES


def with_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute les colonnes calculées (jamais saisies) : région prioritaire et
    jours depuis le dernier mouvement — dérivées uniquement de ce que
    l'utilisateur a saisi, jamais devinées."""
    out = df.copy()
    if out.empty:
        out["Région prioritaire (NOSO / Extrême-Nord)"] = pd.Series(dtype="object")
        out["Jours depuis dernier mouvement"] = pd.Series(dtype="float64")
        return out

    out["Région prioritaire (NOSO / Extrême-Nord)"] = out["Région"].apply(
        lambda r: "Oui" if is_region_prioritaire(r) else "Non"
    )
    dates = pd.to_datetime(out["Date de dernier mouvement"], errors="coerce")
    today = pd.Timestamp(date.today())
    out["Jours depuis dernier mouvement"] = (today - dates).dt.days
    return out
