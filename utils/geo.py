"""Calculs géographiques — uniquement à partir de coordonnées réelles du
classeur. Aucune coordonnée n'est inventée : la position d'une antenne est
un centroïde calculé (moyenne des sites qui lui sont rattachés), pas une
adresse réelle du siège de l'antenne — ce n'est pas fourni dans les
données sources et c'est documenté comme tel partout où c'est affiché."""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1, lon1, lat2, lon2):
    """Distance orthodromique (à vol d'oiseau) entre deux points, en km.
    Accepte des scalaires ou des séries pandas/numpy (vectorisé)."""
    lat1r, lon1r, lat2r, lon2r = (np.radians(x) for x in (lat1, lon1, lat2, lon2))
    dlat = lat2r - lat1r
    dlon = lon2r - lon1r
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1r) * np.cos(lat2r) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


@st.cache_data(show_spinner=False)
def compute_antenna_centroids(sites: pd.DataFrame, antennes_detail: pd.DataFrame) -> pd.DataFrame:
    """Centroïde (barycentre) des sites de chaque antenne — une
    approximation de sa zone de gravité géographique, pas sa localisation
    réelle. Enrichi avec l'effectif recommandé et le type/rattachement
    réels de la feuille « Antennes — Détail solaire »."""
    g = sites.groupby("Antenne proposée").agg(
        Latitude=("Latitude (N)", "mean"),
        Longitude=("Longitude (E)", "mean"),
        Nb_sites_reels=("Nom du site", "count"),
        Puissance_totale=("Puissance (kWc)", "sum"),
    ).reset_index().rename(columns={"Antenne proposée": "Antenne"})

    if antennes_detail is not None and not antennes_detail.empty:
        cols = ["Antenne", "Type", "Rattachée à", "Effectif total", "Sites par agent", "Nb sites"]
        cols = [c for c in cols if c in antennes_detail.columns]
        g = g.merge(antennes_detail[cols], on="Antenne", how="left")
    return g


@st.cache_data(show_spinner=False)
def attach_site_distances(sites: pd.DataFrame, centroids: pd.DataFrame) -> pd.DataFrame:
    """Ajoute à chaque site sa distance orthodromique (km) au centroïde de
    son antenne — un indicateur réel et utile de l'éloignement logistique,
    calculé, jamais inventé."""
    df = sites.merge(
        centroids[["Antenne", "Latitude", "Longitude"]].rename(
            columns={"Latitude": "_ant_lat", "Longitude": "_ant_lon"}
        ),
        left_on="Antenne proposée", right_on="Antenne", how="left",
    )
    df["Distance au centre antenne (km)"] = haversine_km(
        df["Latitude (N)"], df["Longitude (E)"], df["_ant_lat"], df["_ant_lon"]
    ).round(1)
    return df.drop(columns=["_ant_lat", "_ant_lon", "Antenne"])


def hierarchy_edges(centroids: pd.DataFrame) -> list[dict]:
    """Segments (parent -> enfant) pour dessiner la structure hiérarchique
    réelle du réseau (colonne 'Rattachée à') sur la carte. Les antennes
    principales sans parent déclaré sont rattachées visuellement au Siège
    Yaoundé, cohérent avec la feuille Organigramme."""
    if centroids is None or centroids.empty or "Rattachée à" not in centroids.columns:
        return []
    by_name = centroids.set_index("Antenne")
    edges = []
    for name, row in by_name.iterrows():
        if name == "Siège Yaoundé":
            continue
        parent = row.get("Rattachée à")
        parent = parent if parent and str(parent).strip() not in ("—", "None", "", "nan") else "Siège Yaoundé"
        if parent in by_name.index:
            p = by_name.loc[parent]
            edges.append({
                "child": name, "parent": parent,
                "lat": [row["Latitude"], p["Latitude"]],
                "lon": [row["Longitude"], p["Longitude"]],
            })
    return edges
