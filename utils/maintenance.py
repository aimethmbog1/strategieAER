"""Suivi de la maintenance des centrales solaires : arrêts pour panne, dépannages, visites.

Registre « maintenance_interventions » : une ligne par intervention.
- Panne : ouverte au signalement (statut « En panne »), clôturée au dépannage (« Rétablie »).
- Visite : préventive ou de contrôle (statut « Visite »), sans arrêt.
Une centrale est considérée à l'arrêt tant qu'une panne la concernant n'est pas clôturée.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

REGISTRE = "maintenance_interventions"

TYPES = ["Panne (arrêt)", "Visite préventive", "Visite de contrôle"]
STATUTS = ["En panne", "Rétablie", "Visite"]
PROBLEMES = [
    "Batteries (capacité, défaut)",
    "Onduleur / convertisseur",
    "Régulateur de charge",
    "Panneaux PV (casse, salissure, ombrage)",
    "Câblage / connectique",
    "Protections (disjoncteur, fusible, parafoudre)",
    "Réseau de distribution (poteaux, lignes)",
    "Compteurs / système prépayé",
    "Communication / supervision (SIM, datalogger)",
    "Surcharge / court-circuit",
    "Vol / vandalisme",
    "Intempéries (foudre, vent, inondation)",
    "Autre",
]
COLONNES = ["id", "site_id", "site", "phase", "antenne", "puissance_kwc", "type", "statut",
            "date_arret", "date_remise", "duree_arret_h", "problemes", "observations", "actions",
            "date_intervention", "equipe", "chef_equipe", "saisi_par", "saisi_le"]


def registre_vide() -> pd.DataFrame:
    df = pd.DataFrame(columns=COLONNES)
    for c in ("date_arret", "date_remise", "date_intervention", "saisi_le"):
        df[c] = pd.to_datetime(df[c])
    return df


def normaliser(df: pd.DataFrame | None) -> pd.DataFrame:
    """Remet les colonnes et les types attendus (après rechargement depuis la base)."""
    if df is None or df.empty:
        return registre_vide()
    df = df.copy()
    for c in COLONNES:
        if c not in df.columns:
            df[c] = None
    for c in ("date_arret", "date_remise", "date_intervention", "saisi_le"):
        d = pd.to_datetime(df[c], errors="coerce")
        df[c] = d.dt.tz_localize(None) if getattr(d.dt, "tz", None) is not None else d
    for c in ("puissance_kwc", "duree_arret_h"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["id"] = pd.to_numeric(df["id"], errors="coerce").fillna(0).astype(int)
    return df[COLONNES].sort_values("id").reset_index(drop=True)


def referentiel_sites(sites: pd.DataFrame) -> pd.DataFrame:
    """Une ligne par centrale, avec un identifiant unique (le nom seul n'est pas unique dans le parc)."""
    s = sites.copy()
    s["Puissance (kWc)"] = pd.to_numeric(s["Puissance (kWc)"], errors="coerce").fillna(0)
    num = s["N°"].apply(lambda x: str(int(x)) if pd.notna(x) and str(x).replace(".0", "").isdigit() else str(x))
    s["site_id"] = s["Phase"].astype(str) + " · n°" + num + " · " + s["Nom du site"].astype(str)
    s["libelle"] = s["Nom du site"].astype(str) + " (" + s["Phase"].astype(str) + ", " + s["Région"].astype(str) + ")"
    return s


def nouvel_id(reg: pd.DataFrame) -> int:
    return int(reg["id"].max()) + 1 if len(reg) else 1


def duree_heures(debut, fin) -> float | None:
    if pd.isna(debut) or pd.isna(fin):
        return None
    return round((pd.Timestamp(fin) - pd.Timestamp(debut)).total_seconds() / 3600, 1)


def ajouter(reg: pd.DataFrame, lignes: list[dict]) -> pd.DataFrame:
    base = nouvel_id(reg)
    nouv = pd.DataFrame([{**{c: None for c in COLONNES}, **l, "id": base + i} for i, l in enumerate(lignes)])
    return normaliser(pd.concat([reg, nouv], ignore_index=True) if len(reg) else nouv)


def pannes_ouvertes(reg: pd.DataFrame) -> pd.DataFrame:
    return reg[(reg["type"] == TYPES[0]) & (reg["statut"] == "En panne")]


def etat_parc(ref: pd.DataFrame, reg: pd.DataFrame) -> pd.DataFrame:
    """Par phase : centrales, à l'arrêt, fonctionnelles, puissances et ratios."""
    arret = set(pannes_ouvertes(reg)["site_id"])
    r = ref.assign(a_larret=ref["site_id"].isin(arret))
    g = r.groupby("Phase").apply(lambda x: pd.Series({
        "Centrales": len(x),
        "À l'arrêt": int(x["a_larret"].sum()),
        "Fonctionnelles": int((~x["a_larret"]).sum()),
        "Puissance totale (kWc)": round(x["Puissance (kWc)"].sum(), 1),
        "Puissance fonctionnelle (kWc)": round(x.loc[~x["a_larret"], "Puissance (kWc)"].sum(), 1),
    }), include_groups=False).reset_index()
    tot = pd.DataFrame([{"Phase": "Total parc", **g.drop(columns="Phase").sum().to_dict()}])
    g = pd.concat([g, tot], ignore_index=True)
    g["% centrales fonctionnelles"] = (g["Fonctionnelles"] / g["Centrales"] * 100).round(1)
    g["% puissance fonctionnelle"] = (g["Puissance fonctionnelle (kWc)"] / g["Puissance totale (kWc)"] * 100).round(1)
    g["Part de la puissance du parc (%)"] = (g["Puissance totale (kWc)"] / tot["Puissance totale (kWc)"].iloc[0] * 100).round(1)
    for c in ("Centrales", "À l'arrêt", "Fonctionnelles"):
        g[c] = g[c].astype(int)
    return g


def stats_par_centrale(reg: pd.DataFrame, maintenant: pd.Timestamp | None = None) -> pd.DataFrame:
    """Arrêts, durée cumulée, temps moyen de rétablissement et visites, par centrale."""
    maintenant = pd.Timestamp(maintenant) if maintenant is not None else pd.Timestamp(globals()["maintenant"]())
    if reg.empty:
        return pd.DataFrame(columns=["Centrale", "Phase", "Arrêts", "En panne actuellement", "Durée d'arrêt cumulée (h)",
                                     "Temps moyen de rétablissement (h)", "Visites", "Dernière intervention"])
    r = reg.copy()
    pan = r["type"] == TYPES[0]
    # durée : saisie, sinon calculée ; panne ouverte : jusqu'à maintenant
    calc = (r["date_remise"].fillna(maintenant) - r["date_arret"]).dt.total_seconds() / 3600
    r["duree"] = r["duree_arret_h"].where(r["duree_arret_h"].notna() & (r["statut"] != "En panne"), calc).where(pan)
    r["visite"] = (r["date_intervention"].notna()).astype(int)  # tout passage d'équipe (dépannage ou visite)
    g = r.groupby(["site", "phase"]).agg(
        Arrêts=("type", lambda s: int((s == TYPES[0]).sum())),
        **{"En panne actuellement": ("statut", lambda s: "Oui" if (s == "En panne").any() else "Non"),
           "Durée d'arrêt cumulée (h)": ("duree", "sum"),
           "Visites": ("visite", "sum"),
           "Dernière intervention": ("date_intervention", "max")}).reset_index()
    clos = r[pan & (r["statut"] == "Rétablie")].groupby("site")["duree"].mean()
    g["Temps moyen de rétablissement (h)"] = g["site"].map(clos).round(1)
    g["Durée d'arrêt cumulée (h)"] = g["Durée d'arrêt cumulée (h)"].round(1)
    g = g.rename(columns={"site": "Centrale", "phase": "Phase"})
    return g.sort_values(["Arrêts", "Durée d'arrêt cumulée (h)"], ascending=False).reset_index(drop=True)


def stats_par_equipe(reg: pd.DataFrame) -> pd.DataFrame:
    r = reg[reg["equipe"].notna() & (reg["equipe"].astype(str).str.strip() != "")]
    if r.empty:
        return pd.DataFrame(columns=["Équipe", "Sites visités", "Interventions", "Dépannages", "Visites préventives / contrôle",
                                     "Chefs d'équipe"])
    return r.groupby("equipe").agg(
        **{"Sites visités": ("site_id", "nunique"),
           "Interventions": ("id", "count"),
           "Dépannages": ("type", lambda s: int((s == TYPES[0]).sum())),
           "Visites préventives / contrôle": ("type", lambda s: int((s != TYPES[0]).sum())),
           "Chefs d'équipe": ("chef_equipe", lambda s: ", ".join(sorted({str(x) for x in s.dropna() if str(x).strip()})))}
    ).reset_index().rename(columns={"equipe": "Équipe"}).sort_values("Sites visités", ascending=False)


def frequence_problemes(reg: pd.DataFrame) -> pd.DataFrame:
    p = reg["problemes"].dropna().astype(str).str.split("; ").explode().str.strip()
    p = p[p != ""]
    return p.value_counts().rename_axis("Problème").reset_index(name="Occurrences")


def maintenant() -> datetime:
    """Heure locale du Cameroun (le serveur Streamlit Cloud tourne en UTC)."""
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Africa/Douala")).replace(tzinfo=None, second=0, microsecond=0)
