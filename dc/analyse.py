"""Calculs de situation à partir des tables (pandas, sans accès à la base) : écarts ouverts, contrôles en
retard, état par système, indicateurs."""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from .regles import ORDRE, est_en_retard, pire, taux_conformite, taux_respect_plan


def derniers_releves(rel: pd.DataFrame) -> pd.DataFrame:
    """Dernier relevé de chaque contrôle sur chaque équipement."""
    if rel.empty:
        return rel
    return rel.sort_values(["date", "id"]).groupby(["equipement_id", "controle_id"], as_index=False).tail(1)


def ecarts_ouverts(rel: pd.DataFrame) -> pd.DataFrame:
    """Écart ouvert = le dernier relevé d'un contrôle présente une sévérité ; il se referme dès qu'un relevé
    ultérieur du même contrôle est conforme."""
    d = derniers_releves(rel)
    if d.empty:
        return d
    d = d[d["severite"].isin(["Avertissement", "Critique"])]
    return d.assign(_o=d["severite"].map(ORDRE)).sort_values(["_o", "date"], ascending=[False, False]).drop(columns="_o")


def plan_controles(eq: pd.DataFrame, ctl: pd.DataFrame, rel: pd.DataFrame, maintenant: datetime) -> pd.DataFrame:
    """Une ligne par (équipement, contrôle applicable) avec dernière réalisation et retard."""
    if eq.empty or ctl.empty:
        return pd.DataFrame(columns=["equipement_id", "code", "controle_id", "frequence", "derniere", "en_retard"])
    d = derniers_releves(rel)
    dern = {(r.equipement_id, r.controle_id): pd.Timestamp(r.date).to_pydatetime() for r in d.itertuples()} if len(d) else {}
    lignes = []
    for e in eq.itertuples():
        if e.etat in ("Hors service",):
            continue
        cibles = {e.code} | ({e.type_controle} if isinstance(e.type_controle, str) and e.type_controle else set())
        for c in ctl[ctl["cible"].isin(cibles)].itertuples():
            der = dern.get((e.id, c.id))
            lignes.append({"equipement_id": e.id, "code": e.code, "systeme": e.systeme, "controle_id": c.id,
                           "point": c.point, "phase": c.phase, "frequence": c.frequence, "derniere": der,
                           "en_retard": est_en_retard(der, c.frequence, maintenant)})
    return pd.DataFrame(lignes)


def etat_systemes(eq: pd.DataFrame, ecarts: pd.DataFrame, systemes: list[str]) -> pd.DataFrame:
    """Pire sévérité des écarts ouverts par système, et équipements en panne ou dégradés."""
    lignes = []
    for s in systemes:
        e = eq[eq["systeme"] == s]
        ids = set(e["id"])
        ec = ecarts[ecarts["equipement_id"].isin(ids)] if len(ecarts) else ecarts
        sev = pire(list(ec["severite"]) if len(ec) else [])
        if (e["etat"] == "En panne").any():
            sev = pire([sev, "Critique"])
        elif (e["etat"] == "Dégradé").any():
            sev = pire([sev, "Avertissement"])
        lignes.append({"Système": s, "Équipements": len(e), "Écarts ouverts": len(ec),
                       "En panne / dégradés": int(e["etat"].isin(["En panne", "Dégradé"]).sum()),
                       "Informations à compléter": int(e["a_completer"].notna().sum()), "État": sev if len(e) else "—"})
    return pd.DataFrame(lignes)


def indicateurs(plan: pd.DataFrame, rel: pd.DataFrame, depuis: datetime) -> dict:
    r = rel[pd.to_datetime(rel["date"]) >= depuis] if len(rel) else rel
    return {"controles": len(plan), "en_retard": int(plan["en_retard"].sum()) if len(plan) else 0,
            "respect_plan": taux_respect_plan(len(plan), int(plan["en_retard"].sum()) if len(plan) else 0),
            "conformite": taux_conformite(r["severite"]) if len(r) else None,
            "inspections": int(r["inspection_id"].nunique()) if len(r) else 0}


def occupation_baies(eq: pd.DataFrame, hauteur: int = 42) -> tuple[pd.DataFrame, list[str]]:
    """Unités occupées et libres par baie, et chevauchements de positions (erreurs de saisie)."""
    lignes, conflits = [], []
    p = eq[eq["baie"].notna() & eq["u_debut"].notna() & eq["u_fin"].notna()]
    for b, g in p.groupby("baie"):
        occ = {}
        for r in g.itertuples():
            for u in range(int(r.u_debut), int(r.u_fin) + 1):
                if u in occ:
                    conflits.append(f"Baie {b}, U{u} : {occ[u]} et {r.code}")
                occ[u] = r.code
        lignes.append({"Baie": b, "Équipements": len(g), "U occupés": len(occ), "U libres": hauteur - len(occ),
                       "Taux d'occupation (%)": round(100 * len(occ) / hauteur, 1)})
    return pd.DataFrame(lignes), conflits
