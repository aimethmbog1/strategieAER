"""Lecture et contrôle du classeur « Suivi des recharges des abonnés — Data Center ».

Sources reconnues dans le classeur :
- `Saisie_Journaliere` (une ligne par jour) : agrégée par mois si elle contient des données ;
- sinon `Recap_Mensuel` (une ligne par mois, colonnes A à H).
"""
from __future__ import annotations

import io

import pandas as pd
import streamlit as st

MOIS_LONGS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
              "octobre", "novembre", "décembre"]
MOIS_FR = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
PRIX_KWH_REFERENCE = 100.0  # FCFA/kWh observé sur l'historique (recettes / énergie)


def _col(df: pd.DataFrame, *motifs: str) -> str | None:
    for c in df.columns:
        nom = str(c).lower()
        if all(m in nom for m in motifs):
            return c
    return None


def _depuis_saisie_journaliere(raw: pd.DataFrame) -> pd.DataFrame:
    c_date = _col(raw, "date")
    if c_date is None:
        return pd.DataFrame()
    d = raw.copy()
    d["date"] = pd.to_datetime(d[c_date], errors="coerce", dayfirst=True)
    d = d.dropna(subset=["date"])
    if d.empty:
        return pd.DataFrame()
    c_cli, c_kwh, c_mnt = _col(d, "client"), _col(d, "énergie") or _col(d, "energie"), _col(d, "montant")
    g = d.groupby(d["date"].dt.to_period("M"))
    out = pd.DataFrame({
        "nb_jours": g.size(),
        "clients": g[c_cli].mean() if c_cli else None,
        "energie_kwh": g[c_kwh].sum() if c_kwh else None,
        "recettes": g[c_mnt].sum() if c_mnt else None,
    })
    out.index = out.index.to_timestamp()
    out = out.reset_index(names="mois")
    return out


def _depuis_recap(raw: pd.DataFrame) -> pd.DataFrame:
    raw = raw.iloc[:, :8]
    raw.columns = ["annee", "num_mois", "libelle", "nb_jours", "clients", "energie_kwh", "cumul_kwh", "recettes"]
    d = raw.dropna(subset=["annee", "num_mois"]).copy()
    d["annee"] = pd.to_numeric(d["annee"], errors="coerce")
    d["num_mois"] = pd.to_numeric(d["num_mois"], errors="coerce")
    d = d.dropna(subset=["annee", "num_mois"])
    d["mois"] = pd.to_datetime(dict(year=d["annee"].astype(int), month=d["num_mois"].astype(int), day=1))
    for c in ("nb_jours", "clients", "energie_kwh", "recettes"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    return d[["mois", "nb_jours", "clients", "energie_kwh", "recettes"]]


@st.cache_data(show_spinner=False, max_entries=16)
def lire_classeur_recharges(contenu: bytes) -> pd.DataFrame:
    """Renvoie une ligne par mois renseigné : mois, nb_jours, clients, energie_kwh, recettes,
    + colonnes dérivées (annee, mois_num, libelle, prix_kwh, kwh_par_client)."""
    xls = pd.ExcelFile(io.BytesIO(contenu))
    d = pd.DataFrame()
    if "Saisie_Journaliere" in xls.sheet_names:
        d = _depuis_saisie_journaliere(pd.read_excel(xls, "Saisie_Journaliere"))
    if d.empty and "Recap_Mensuel" in xls.sheet_names:
        d = _depuis_recap(pd.read_excel(xls, "Recap_Mensuel"))
    if d.empty:
        raise ValueError("Ni l'onglet « Saisie_Journaliere » ni l'onglet « Recap_Mensuel » ne contiennent de données.")
    d = d[d["recettes"].fillna(0) > 0].sort_values("mois").reset_index(drop=True)
    return enrichir(d[["mois", "nb_jours", "clients", "energie_kwh", "recettes"]])


COLONNES_BASE = ["mois", "nb_jours", "clients", "energie_kwh", "recettes"]


def enrichir(d: pd.DataFrame) -> pd.DataFrame:
    """Ajoute les colonnes dérivées à partir des colonnes de base (aussi après rechargement du stockage)."""
    d = d.copy()
    mois = pd.to_datetime(d["mois"])
    if mois.dt.tz is not None:
        mois = mois.dt.tz_localize(None)
    d["mois"] = mois
    d = d.sort_values("mois").reset_index(drop=True)
    d["annee"] = d["mois"].dt.year
    d["mois_num"] = d["mois"].dt.month
    d["libelle"] = d["mois_num"].map(lambda m: MOIS_FR[m - 1]) + "-" + d["annee"].astype(str)
    d["prix_kwh"] = d["recettes"] / d["energie_kwh"]
    d["kwh_par_client"] = d["energie_kwh"] / d["clients"]
    return d


def _n(x) -> str:
    return f"{x:,.0f}".replace(",", " ")


def controles_qualite(d: pd.DataFrame, aujourd_hui: pd.Timestamp | None = None) -> pd.DataFrame:
    """Signale les mois à vérifier dans la source. Ne corrige rien."""
    aujourd_hui = aujourd_hui or pd.Timestamp.today()
    alertes = []
    med_cli = d["clients"].median()
    for _, r in d.iterrows():
        lib = r["libelle"]
        if r["mois"].to_period("M") == aujourd_hui.to_period("M"):
            alertes.append((lib, "Mois en cours", "Mois incomplet : à ne pas comparer aux mois complets."))
        if pd.notna(r["clients"]) and pd.notna(r["energie_kwh"]) and r["clients"] == r["energie_kwh"]:
            alertes.append((lib, "Saisie suspecte",
                            f"Clients ({_n(r['clients'])}) identique à l'énergie ({_n(r['energie_kwh'])} kWh) : "
                            "colonne probablement mal recopiée."))
        elif pd.notna(r["clients"]) and med_cli and not (med_cli / 3 <= r["clients"] <= med_cli * 3):
            alertes.append((lib, "Valeur atypique",
                            f"Clients = {_n(r['clients'])}, loin de la médiane ({_n(med_cli)})."))
        if pd.notna(r["prix_kwh"]) and abs(r["prix_kwh"] - PRIX_KWH_REFERENCE) > 5:
            alertes.append((lib, "Prix moyen inhabituel",
                            f"{r['prix_kwh']:.1f} FCFA/kWh (référence ≈ {PRIX_KWH_REFERENCE:.0f})."))
    return pd.DataFrame(alertes, columns=["Mois", "Type", "Détail"])


def mois_complets(d: pd.DataFrame, aujourd_hui: pd.Timestamp | None = None) -> pd.DataFrame:
    aujourd_hui = aujourd_hui or pd.Timestamp.today()
    return d[d["mois"].dt.to_period("M") < aujourd_hui.to_period("M")]
