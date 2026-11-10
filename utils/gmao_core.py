"""GMAO — modèle de données et calculs (demandes, bons d'intervention, préventif, stocks, achats, budgets).

Registres (base de données) :
  gmao_di            demandes d'intervention (DI)
  gmao_bi            bons d'intervention / ordres de travail (BI)
  gmao_plans         gammes de maintenance préventive (périodicité, périmètre)
  gmao_articles      catalogue des pièces (stock mini, prix)
  gmao_mouvements    entrées / sorties / ajustements de stock
  gmao_achats        demandes d'achat et commandes
  gmao_budget        budget de maintenance par année et par poste
  gmao_prestataires  prestataires et contrats
  gmao_equipements   équipements détaillés ajoutés à l'arborescence site > système
Les journaux importés (« Maintenance log followup ») restent dans les registres gmao_defauts / gmao_statuts.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from .storage import mettre_a_jour, session_ou_stockage

SYSTEMES = ["Champ PV", "Stockage (batteries)", "Conversion (onduleurs, MDU, HSU)", "Refroidissement / ventilation",
            "Réseau de distribution", "Protections", "Comptage", "Supervision / communication", "Génie civil / clôture"]
CATEGORIE_VERS_SYSTEME = {
    "Champ PV": "Champ PV", "Champ PV (structure)": "Champ PV", "Nettoyage": "Champ PV",
    "Système de batterie": "Stockage (batteries)", "Batteries": "Stockage (batteries)",
    "Conversion (onduleurs, MDU…)": "Conversion (onduleurs, MDU, HSU)", "Refroidissement": "Refroidissement / ventilation",
    "Réseau de distribution": "Réseau de distribution", "Protections": "Protections", "Comptage": "Comptage",
    "Capteurs / supervision": "Supervision / communication", "Génie civil / clôture": "Génie civil / clôture",
}
TYPES_BI = ["Corrective", "Préventive", "Réglementaire / inspection", "Amélioration"]
PRIORITES = ["Critique", "Urgente", "Majeure", "Mineure"]
STATUTS_DI = ["Nouvelle", "Acceptée", "Refusée", "Annulée"]
STATUTS_BI = ["À planifier", "Planifié", "En cours", "En attente de pièces", "Terminé", "Clôturé", "Annulé"]
STATUTS_BI_OUVERTS = ["À planifier", "Planifié", "En cours", "En attente de pièces"]
STATUTS_ACHAT = ["Demande", "Validée", "Commandée", "Reçue", "Annulée"]
POSTES_BUDGET = ["Pièces de rechange", "Main d'œuvre", "Prestataires", "Déplacements / carburant", "Outillage"]
MAGASINS = ["Magasin central (Yaoundé)", "Antenne Nord", "Antenne Extrême-Nord", "Antenne Adamaoua", "Antenne Est",
            "Antenne Ouest", "Antenne Sud", "Antenne Littoral"]

COLS = {
    "gmao_di": ["id", "date", "demandeur", "site_id", "site", "phase", "region", "systeme", "equipement", "description",
                "priorite", "centrale_arret", "statut", "bi_id", "motif"],
    "gmao_bi": ["id", "di_id", "origine", "plan_id", "type", "priorite", "site_id", "site", "phase", "region", "systeme",
                "equipement", "description", "statut", "centrale_arret", "date_creation", "date_prevue", "date_debut",
                "date_fin", "date_arret", "date_remise", "duree_interv_h", "temps_arret_h", "equipe", "chef",
                "intervenants", "travaux", "cause", "cout_mo", "cout_presta", "prestataire"],
    "gmao_plans": ["id", "libelle", "type", "systeme", "phases", "regions", "periodicite_j", "duree_h", "equipe",
                   "prochaine_echeance", "actif", "consignes"],
    "gmao_articles": ["code", "designation", "categorie", "systeme", "unite", "magasin", "stock_mini", "prix_unitaire"],
    "gmao_mouvements": ["id", "date", "code", "type", "quantite", "magasin", "bi_id", "achat_id", "motif", "auteur"],
    "gmao_achats": ["id", "date", "code", "designation", "quantite", "fournisseur", "prix_unitaire", "montant", "statut",
                    "date_reception", "bi_id", "commentaire"],
    "gmao_budget": ["annee", "poste", "montant_prevu"],
    "gmao_prestataires": ["nom", "domaine", "contact", "fin_contrat", "notes"],
    "gmao_equipements": ["id", "site_id", "site", "systeme", "designation", "marque_modele", "numero_serie", "quantite",
                         "date_mes", "criticite", "statut", "notes"],
}
DATES = {"date", "date_creation", "date_prevue", "date_debut", "date_fin", "date_arret", "date_remise",
         "prochaine_echeance", "date_reception", "fin_contrat", "date_mes"}
NUMS = {"duree_interv_h", "temps_arret_h", "cout_mo", "cout_presta", "periodicite_j", "duree_h", "stock_mini",
        "prix_unitaire", "quantite", "montant", "montant_prevu", "annee"}


def maintenant() -> datetime:
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Africa/Douala")).replace(tzinfo=None, second=0, microsecond=0)


def _normaliser(nom: str, df: pd.DataFrame | None) -> pd.DataFrame:
    cols = COLS[nom]
    df = pd.DataFrame(columns=cols) if df is None or len(df) == 0 else df.copy()
    for c in cols:
        if c not in df.columns:
            df[c] = None
    for c in cols:
        if c in DATES:
            x = pd.to_datetime(df[c], errors="coerce")
            df[c] = x.dt.tz_localize(None) if getattr(x.dt, "tz", None) is not None else x
        elif c in NUMS:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        elif c in ("centrale_arret", "actif"):
            df[c] = df[c].fillna(False).astype(bool)
    return df[cols]


def table(nom: str) -> pd.DataFrame:
    df = session_ou_stockage(nom, lambda: pd.DataFrame(columns=COLS[nom]))
    return _normaliser(nom, df)


def sauver(nom: str, df: pd.DataFrame, detail: str) -> bool:
    return mettre_a_jour(nom, _normaliser(nom, df), detail)


def nouvel_id(df: pd.DataFrame, prefixe: str) -> str:
    an = maintenant().year
    deja = df["id"].dropna().astype(str)
    nums = deja[deja.str.startswith(f"{prefixe}-{an}-")].str.split("-").str[-1].astype(int)
    return f"{prefixe}-{an}-{(nums.max() + 1 if len(nums) else 1):04d}"


def ajouter(nom: str, lignes: list[dict], prefixe: str | None, detail: str) -> list[str]:
    df = table(nom)
    ids = []
    for l in lignes:
        if prefixe:
            l = {**l, "id": nouvel_id(df, prefixe)}
            ids.append(l["id"])
        df = pd.concat([df, pd.DataFrame([{c: l.get(c) for c in COLS[nom]}])], ignore_index=True)
    sauver(nom, df, detail)
    return ids


def modifier(nom: str, ident: str, valeurs: dict, detail: str, cle: str = "id") -> None:
    df = table(nom)
    i = df.index[df[cle].astype(str) == str(ident)]
    if len(i):
        for k, v in valeurs.items():
            df.loc[i[0], k] = v
        sauver(nom, df, detail)


# ------------------------------------------------------------------ migration des saisies existantes
def migrer_interventions() -> int:
    """Reprend une fois les saisies de l'ancien suivi (registre maintenance_interventions) en bons d'intervention."""
    from .storage import charger
    if st.session_state.get("_gmao_migre"):
        return 0
    st.session_state["_gmao_migre"] = True
    bi = table("gmao_bi")
    if (bi["origine"] == "Reprise ancien suivi").any():
        return 0
    old = charger("maintenance_interventions")
    if old is None or old.empty:
        return 0
    lignes = []
    for _, r in old.iterrows():
        panne = r.get("type") == "Panne (arrêt)"
        clos = r.get("statut") in ("Rétablie", "Visite")
        lignes.append({"origine": "Reprise ancien suivi", "type": "Corrective" if panne else "Préventive",
                       "priorite": "Majeure", "site_id": r.get("site_id"), "site": r.get("site"), "phase": r.get("phase"),
                       "description": r.get("problemes") or r.get("observations"), "statut": "Clôturé" if clos else "En cours",
                       "centrale_arret": bool(panne), "date_creation": r.get("date_arret") or r.get("date_intervention"),
                       "date_arret": r.get("date_arret") if panne else None, "date_remise": r.get("date_remise"),
                       "date_fin": r.get("date_intervention"), "temps_arret_h": r.get("duree_arret_h"),
                       "equipe": r.get("equipe"), "chef": r.get("chef_equipe"), "travaux": r.get("actions")})
    ajouter("gmao_bi", lignes, "BI", f"reprise de {len(lignes)} saisie(s) de l'ancien suivi de maintenance")
    return len(lignes)


# ------------------------------------------------------------------ stocks
def niveaux_stock() -> pd.DataFrame:
    art = table("gmao_articles")
    mv = table("gmao_mouvements")
    if art.empty:
        return pd.DataFrame(columns=["code", "designation", "categorie", "unite", "stock", "stock_mini", "prix_unitaire",
                                     "valeur", "alerte"])
    signe = mv["type"].map({"Entrée": 1, "Sortie": -1, "Ajustement": 1}).fillna(0)
    st_ = (mv["quantite"].fillna(0) * signe).groupby(mv["code"]).sum()
    out = art.copy()
    out["stock"] = out["code"].map(st_).fillna(0)
    out["valeur"] = out["stock"] * out["prix_unitaire"].fillna(0)
    mini = out["stock_mini"].fillna(0)
    out["alerte"] = (mini > 0) & (out["stock"] <= mini)
    return out


def cout_pieces_par_bi() -> pd.Series:
    mv = table("gmao_mouvements")
    art = table("gmao_articles").set_index("code")["prix_unitaire"]
    s = mv[(mv["type"] == "Sortie") & mv["bi_id"].notna()]
    return (s["quantite"] * s["code"].map(art).fillna(0)).groupby(s["bi_id"]).sum()


# ------------------------------------------------------------------ préventif
def generer_preventif(ref_sites: pd.DataFrame, horizon_j: int = 30) -> int:
    """Crée les BI préventifs des gammes actives arrivant à échéance dans l'horizon, puis avance les échéances."""
    plans = table("gmao_plans")
    if plans.empty:
        return 0
    limite = pd.Timestamp(maintenant()) + pd.Timedelta(days=horizon_j)
    lignes, maj = [], plans.copy()
    for i, p in plans[plans["actif"]].iterrows():
        ech = p["prochaine_echeance"]
        if pd.isna(ech) or ech > limite:
            continue
        s = ref_sites
        if p["phases"]:
            s = s[s["Phase"].isin(str(p["phases"]).split("; "))]
        if p["regions"]:
            s = s[s["Région"].isin(str(p["regions"]).split("; "))]
        while ech <= limite:
            for _, r in s.iterrows():
                lignes.append({"origine": "Préventif", "plan_id": p["id"], "type": p["type"] or "Préventive",
                               "priorite": "Mineure", "site_id": r["site_id"], "site": r["Nom du site"], "phase": r["Phase"],
                               "region": r["Région"], "systeme": p["systeme"], "description": p["libelle"],
                               "statut": "Planifié" if p["equipe"] else "À planifier",
                               "date_creation": pd.Timestamp(maintenant()), "date_prevue": ech,
                               "duree_interv_h": p["duree_h"], "equipe": p["equipe"], "travaux": p["consignes"]})
            ech = ech + pd.Timedelta(days=int(p["periodicite_j"] or 30))
        maj.loc[i, "prochaine_echeance"] = ech
    if lignes:
        ajouter("gmao_bi", lignes, "BI", f"génération du préventif : {len(lignes)} BI planifié(s)")
        sauver("gmao_plans", maj, "échéances des gammes préventives avancées")
    return len(lignes)


# ------------------------------------------------------------------ indicateurs
def kpis_bi(bi: pd.DataFrame, aujourd_hui: pd.Timestamp) -> dict:
    ouverts = bi[bi["statut"].isin(STATUTS_BI_OUVERTS)]
    fermes = bi[bi["statut"].isin(["Terminé", "Clôturé"])]
    corr = bi[bi["type"] == "Corrective"]
    prev = bi[bi["type"] != "Corrective"]
    arr = fermes[(fermes["type"] == "Corrective") & fermes["temps_arret_h"].notna()]
    avec_prevu = fermes[fermes["date_prevue"].notna() & fermes["date_fin"].notna()]
    en_retard = ouverts[ouverts["date_prevue"].notna() & (ouverts["date_prevue"] < aujourd_hui)]
    return {
        "total": len(bi), "ouverts": len(ouverts), "fermes": len(fermes), "en_retard": len(en_retard),
        "non_affectes": int((ouverts["equipe"].isna() | (ouverts["equipe"].astype(str).str.strip() == "")).sum()),
        "part_preventif": len(prev) / len(bi) * 100 if len(bi) else None,
        "mttr_h": arr["temps_arret_h"].mean() if len(arr) else None,
        "duree_moy_h": fermes["duree_interv_h"].mean() if fermes["duree_interv_h"].notna().any() else None,
        "respect_planning": (avec_prevu["date_fin"].dt.normalize() <= avec_prevu["date_prevue"]).mean() * 100
        if len(avec_prevu) else None,
        "centrales_arret": ouverts.loc[ouverts["centrale_arret"], "site_id"].nunique(),
        "correctifs": len(corr), "preventifs": len(prev),
    }


def disponibilite_sites(bi: pd.DataFrame, debut: pd.Timestamp, fin: pd.Timestamp) -> pd.DataFrame:
    """Temps d'arrêt (BI correctifs avec arrêt) et disponibilité par centrale sur la période."""
    c = bi[(bi["type"] == "Corrective") & bi["centrale_arret"] & bi["date_arret"].notna()].copy()
    if c.empty:
        return pd.DataFrame(columns=["Centrale", "Arrêts", "Temps d'arrêt (h)", "Disponibilité (%)"])
    c["d0"] = c["date_arret"].clip(lower=debut)
    c["d1"] = c["date_remise"].fillna(pd.Timestamp(maintenant())).clip(upper=fin)
    c = c[c["d1"] > c["d0"]]
    c["h"] = (c["d1"] - c["d0"]).dt.total_seconds() / 3600
    periode_h = max((fin - debut).total_seconds() / 3600, 1)
    g = c.groupby("site").agg(Arrêts=("id", "count"), **{"Temps d'arrêt (h)": ("h", "sum")}).reset_index()
    g["Disponibilité (%)"] = (100 - g["Temps d'arrêt (h)"] / periode_h * 100).clip(lower=0).round(2)
    g["Temps d'arrêt (h)"] = g["Temps d'arrêt (h)"].round(1)
    return g.rename(columns={"site": "Centrale"}).sort_values("Temps d'arrêt (h)", ascending=False)


def couts_bi(bi: pd.DataFrame) -> pd.DataFrame:
    b = bi.copy()
    b["cout_pieces"] = b["id"].map(cout_pieces_par_bi()).fillna(0)
    b["cout_total"] = b["cout_mo"].fillna(0) + b["cout_presta"].fillna(0) + b["cout_pieces"]
    return b


def execution_budget(annee: int) -> pd.DataFrame:
    bud = table("gmao_budget")
    bud = bud[bud["annee"] == annee]
    b = couts_bi(table("gmao_bi"))
    b = b[b["date_fin"].dt.year == annee]
    ach = table("gmao_achats")
    ach = ach[(ach["date"].dt.year == annee) & ach["statut"].isin(["Commandée", "Reçue"])]
    realise = {"Pièces de rechange": b["cout_pieces"].sum(), "Main d'œuvre": b["cout_mo"].sum(),
               "Prestataires": b["cout_presta"].sum()}
    engage = {"Pièces de rechange": ach["montant"].sum()}
    postes = list(dict.fromkeys(POSTES_BUDGET + bud["poste"].dropna().tolist()))
    out = pd.DataFrame({"Poste": postes})
    out["Budget prévu"] = out["Poste"].map(dict(zip(bud["poste"], bud["montant_prevu"]))).fillna(0)
    out["Engagé (commandes)"] = out["Poste"].map(engage).fillna(0)
    out["Réalisé (BI)"] = out["Poste"].map(realise).fillna(0)
    out["Disponible"] = out["Budget prévu"] - out[["Engagé (commandes)", "Réalisé (BI)"]].max(axis=1)
    out["Taux de consommation (%)"] = (out[["Engagé (commandes)", "Réalisé (BI)"]].max(axis=1) / out["Budget prévu"] * 100
                                       ).where(out["Budget prévu"] > 0).round(1)
    return out


def initialiser_articles_depuis_journaux(defauts: pd.DataFrame) -> int:
    """Catalogue de départ : un article par code matériel rencontré dans les journaux (stock à 0)."""
    art = table("gmao_articles")
    if not art.empty or defauts is None or defauts.empty:
        return 0
    d = defauts.dropna(subset=["code_materiel"])
    d = d[d["code_materiel"].astype(str).str.match(r"^[A-Z]{1,3}-\d+")]
    cat = d.groupby("code_materiel").agg(designation=("materiel", lambda s: s.mode().iloc[0]),
                                          categorie=("categorie", lambda s: s.mode().iloc[0])).reset_index()
    lignes = [{"code": r["code_materiel"], "designation": r["designation"], "categorie": r["categorie"],
               "systeme": CATEGORIE_VERS_SYSTEME.get(r["categorie"]), "unite": "u", "magasin": MAGASINS[0],
               "stock_mini": 0, "prix_unitaire": 0} for _, r in cat.iterrows()]
    if lignes:
        ajouter("gmao_articles", lignes, None, f"catalogue initial : {len(lignes)} articles issus des journaux")
    return len(lignes)
