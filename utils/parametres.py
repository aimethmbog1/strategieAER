"""Réglages saisis dans les pages (seuils, phases, objectifs, options…) conservés dans la base.

Un seul registre « parametres_pages » : une ligne par (page, clé), valeur sérialisée en JSON
(dates et tableaux compris). Les filtres d'affichage (recherche, sélection de période à l'écran)
ne sont volontairement pas enregistrés : ce sont des choix de lecture, pas des données.

Usage :
    seuil = valeur("alertes", "seuil", 60)
    ...widget...
    memoriser("alertes", "seuil", seuil)   # n'écrit que si la valeur a changé
"""
from __future__ import annotations

import json
from datetime import date, datetime

import pandas as pd
import streamlit as st

from .storage import charger, enregistrer

REGISTRE = "parametres_pages"
_COLS = ["page", "cle", "valeur", "maj"]


def _encoder(o):
    if isinstance(o, pd.DataFrame):
        o = o.copy()
        for c in o.columns:  # colonnes de dates Python : typées explicitement pour revenir en dates
            nn = o[c].dropna()
            if o[c].dtype == object and len(nn) and all(isinstance(x, (date, datetime)) for x in nn):
                o[c] = pd.to_datetime(o[c])
        return {"__df__": o.to_json(orient="table", date_format="iso")}
    if isinstance(o, datetime):
        return {"__dt__": o.isoformat()}
    if isinstance(o, date):
        return {"__date__": o.isoformat()}
    if hasattr(o, "item"):  # types numpy
        return o.item()
    raise TypeError(f"Type non sérialisable : {type(o)}")


def _decoder(d: dict):
    if "__df__" in d:
        from io import StringIO
        df = pd.read_json(StringIO(d["__df__"]), orient="table")
        for c in df.columns:  # les colonnes de dates reviennent en datetime : on rend des dates simples
            if pd.api.types.is_datetime64_any_dtype(df[c]):
                df[c] = df[c].dt.tz_localize(None).dt.date if df[c].dt.tz is not None else df[c].dt.date
        return df
    if "__dt__" in d:
        return datetime.fromisoformat(d["__dt__"])
    if "__date__" in d:
        return date.fromisoformat(d["__date__"])
    return d


def _table() -> pd.DataFrame:
    if REGISTRE not in st.session_state:
        df = charger(REGISTRE)
        st.session_state[REGISTRE] = df if df is not None and not df.empty else pd.DataFrame(columns=_COLS)
    return st.session_state[REGISTRE]


def valeur(page: str, cle: str, defaut=None):
    """Valeur enregistrée pour (page, clé), sinon `defaut`."""
    t = _table()
    m = t[(t["page"] == page) & (t["cle"] == cle)]
    if m.empty:
        return defaut
    try:
        return json.loads(m["valeur"].iloc[0], object_hook=_decoder)
    except Exception:  # noqa: BLE001 — valeur illisible : on revient au défaut
        return defaut


def memoriser(page: str, cle: str, val) -> None:
    """Enregistre (page, clé) dans la base si la valeur a changé. Silencieux pour un profil en lecture seule."""
    from .auth import peut_modifier
    try:
        texte = json.dumps(val, default=_encoder, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return
    t = _table()
    m = (t["page"] == page) & (t["cle"] == cle)
    if m.any() and t.loc[m, "valeur"].iloc[0] == texte:
        return
    if not peut_modifier():
        return
    t = t[~m]
    t = pd.concat([t, pd.DataFrame([{"page": page, "cle": cle, "valeur": texte,
                                     "maj": datetime.now().isoformat(timespec="seconds")}])], ignore_index=True)
    st.session_state[REGISTRE] = t
    enregistrer(REGISTRE, t, f"réglage « {cle} » — page {page}")
