"""Données et logique du Fonds revolving (Composante 3 du PERACE — aide au
financement des frais de raccordement des ménages).

Important — ce module ne contient AUCUNE donnée financière ou de dossier
réelle : le classeur Excel du tableau de bord AER (Gestion_Parc_Solaire...)
ne comporte aucune feuille sur ce fonds, qui est un mécanisme distinct,
financé par la Banque mondiale (crédit IDA, Composante 3 du PERACE) et géré
par l'AER, mais concernant l'électrification par extension réseau (raccor-
dements ENEO), pas le parc de mini-centrales solaires documenté ailleurs
dans l'application.

Ce qui est réel et fourni ici :
  - la répartition du personnel de suivi (délégations régionales/commerciales
    et noms), telle que communiquée par l'utilisateur.
Ce qui est un outil à alimenter, pas une donnée déjà connue :
  - le registre des dossiers de raccordement (aucun dossier n'est préchargé ;
    l'utilisateur les saisit au fur et à mesure, et peut sauvegarder/recharger
    son registre via un fichier CSV, faute de base de données persistante
    dans cet environnement Streamlit).
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from .storage import mettre_a_jour, session_ou_stockage

# ---------------------------------------------------------------------------
# Répartition du personnel de suivi du fonds (donnée réelle, fournie par
# l'utilisateur — organisation par délégation régionale ENEO / AER, distincte
# de la taxonomie des « antennes » du réseau solaire utilisée ailleurs dans
# l'application).
# ---------------------------------------------------------------------------
_RAW_STAFF: list[tuple[str, str, list[str]]] = [
    ("DCUD", "Douala-Centre, Douala-Est", ["EWANE WANG Roméo", "NGUIDJOL Stelle Philomène"]),
    ("DCUD", "Douala-Nord, Douala-Ouest, Douala-Sud", ["Essono Léandre Simplice", "ATENGONG Javan Javan"]),
    ("DCUY", "Yaoundé-Centre, Yaoundé-Nord", ["TCHOUWA YONSI Rostand", "NJIKE Vidale"]),
    ("DCUY", "Yaoundé-Ouest, Yaoundé-Sud", ["ZOA AMBASSA Maxime Joel", "Brenda BIBAI NDIGUI"]),
    ("DRC", "Bafia, Mfou, Obala", ["MVOMO AZEME Franck", "YENGO Derrick NGUM"]),
    ("DRE", "Bertoua", ["NONGA NDOUM Joseph", "MBELLE Ben Thierry"]),
    ("DRE", "Est EXT", ["AKONO ESSOUMA Cedric", "TSALA Chris Hyacinthe Ferdinand"]),
    ("DRNEA", "Nord, Extrême-Nord", ["ABDOULAYE AWAH Sallam", "HAMADOU MOUSSA"]),
    ("DRNEA", "Adamaoua", ["ABBA ILYASSA", "TIAM TIAGHOUE Valery"]),
    ("DRONO", "Bamenda, Bamenda EXT", ["NGANDI FUL Nelson", "NGUM Richard"]),
    ("DRONO", "Ouest 1-Noun, Ouest 1-Baf, Ouest 2-Men_Bamb, Ouest 2-Haut-Nkam",
     ["TAGNE CHIETEU Duclair", "CHIA Gabriel"]),
    ("DRSANO", "Edea, Eseka, Kribi", ["HAPPY NYEMECK Rene", "MBENGIE Maxwell"]),
    ("DRSM", "Ebolowa, Mbalmayo, Sangmelima", ["ABBO ISMAILA", "SONDECK Ludovic"]),
    ("DRSOM", "Kumba, Limbe, Moungo", ["TANG ELIAS BESONG", "TABOT ENOH EQUINE"]),
]


def staff_table() -> pd.DataFrame:
    """Une ligne par agent (délégation régionale, délégation commerciale, agent)."""
    rows = []
    for region, commercial, agents in _RAW_STAFF:
        for agent in agents:
            rows.append({
                "Délégation régionale": region,
                "Délégation commerciale": commercial,
                "Agent": agent,
            })
    return pd.DataFrame(rows)


def regions() -> list[str]:
    seen = []
    for region, _, _ in _RAW_STAFF:
        if region not in seen:
            seen.append(region)
    return seen


def commercial_zones(region: str) -> list[str]:
    return [c for r, c, _ in _RAW_STAFF if r == region]


def agents_for(region: str, commercial: str) -> list[str]:
    for r, c, agents in _RAW_STAFF:
        if r == region and c == commercial:
            return list(agents)
    return []


def all_agents() -> list[str]:
    out = []
    for _, _, agents in _RAW_STAFF:
        out.extend(agents)
    return out


# ---------------------------------------------------------------------------
# Registre des dossiers de raccordement — vide par défaut, alimenté et
# maintenu en mémoire de session (st.session_state), exportable/importable
# en CSV pour persister d'une session à l'autre.
# ---------------------------------------------------------------------------
REGISTER_COLUMNS = [
    "N° dossier",
    "Date d'enregistrement",
    "Délégation régionale",
    "Délégation commerciale",
    "Agent en charge",
    "Localité / site",
    "Coût total du raccordement (FCFA)",
    "Frais initial payé par le ménage (FCFA)",
    "Durée de remboursement (ans)",
    "Montant remboursé à ce jour (FCFA)",
    "Statut",
    "Notes",
]

STATUTS = ["En cours", "Soldé", "En retard", "Litige"]

# Valeurs de référence documentées pour la Composante 3 du PERACE (source :
# document de projet Banque mondiale P163881 et rapports de suivi — voir
# l'encadré méthodologique de la page). Utilisées comme valeurs par défaut
# du formulaire, jamais comme des données déjà enregistrées.
FRAIS_INITIAL_REFERENCE_FCFA = 2000
DUREE_REMBOURSEMENT_REFERENCE_ANS = [6, 7, 8]


def empty_register() -> pd.DataFrame:
    df = pd.DataFrame(columns=REGISTER_COLUMNS)
    df["Date d'enregistrement"] = pd.to_datetime(df["Date d'enregistrement"])
    for c in ["Coût total du raccordement (FCFA)", "Frais initial payé par le ménage (FCFA)",
              "Durée de remboursement (ans)", "Montant remboursé à ce jour (FCFA)"]:
        df[c] = pd.to_numeric(df[c])
    return df


def get_register() -> pd.DataFrame:
    # registre durable : rechargé depuis le stockage (utils/storage.py) au début de chaque session
    return session_ou_stockage("revolving_register", empty_register)


def set_register(df: pd.DataFrame) -> None:
    mettre_a_jour("revolving_register", df)


def next_dossier_id(df: pd.DataFrame) -> str:
    n = len(df) + 1
    today = date.today().strftime("%Y")
    return f"FR-{today}-{n:04d}"


def with_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute les colonnes calculées (jamais saisies) : montant à rembourser,
    solde restant dû, taux de recouvrement — dérivées uniquement des montants
    que l'utilisateur a lui-même saisis dans le registre."""
    out = df.copy()
    if out.empty:
        out["Montant à rembourser (FCFA)"] = pd.Series(dtype="float64")
        out["Solde restant dû (FCFA)"] = pd.Series(dtype="float64")
        out["Taux de recouvrement (%)"] = pd.Series(dtype="float64")
        return out

    cout = pd.to_numeric(out["Coût total du raccordement (FCFA)"], errors="coerce").fillna(0)
    initial = pd.to_numeric(out["Frais initial payé par le ménage (FCFA)"], errors="coerce").fillna(0)
    rembourse = pd.to_numeric(out["Montant remboursé à ce jour (FCFA)"], errors="coerce").fillna(0)

    a_rembourser = (cout - initial).clip(lower=0)
    solde = (a_rembourser - rembourse).clip(lower=0)
    taux = (rembourse / a_rembourser.replace(0, pd.NA) * 100).fillna(0).clip(upper=100)

    out["Montant à rembourser (FCFA)"] = a_rembourser
    out["Solde restant dû (FCFA)"] = solde
    out["Taux de recouvrement (%)"] = taux.round(1)
    return out
