"""GMAO — import des journaux de maintenance (« Maintenance log followup ») et indicateurs.

Feuilles exploitées dans chaque classeur :
- « Toutes les Défauts-350 »  : journal des défauts (une ligne par défaut constaté) ;
- « Status 350 localite »     : état de fonctionnement de chaque centrale (Phases 1 et 2) ;
- « TEMPS DE FONTIONNEMENT »  : plages horaires paramétrées (classeur 2026) ;
- « Inspection Checklist »    : inspections datées ;
- « Repartition »             : zone et responsable de chaque site.
Les colonnes de contact (fonction, téléphone) ne sont pas importées.
"""
from __future__ import annotations

import io
import re
import unicodedata

import pandas as pd

REG_DEFAUTS = "gmao_defauts"
REG_STATUTS = "gmao_statuts"
REG_INSPECTIONS = "gmao_inspections"
REG_AFFECTATIONS = "gmao_affectations"

REGIONS_FR = {"adamawa": "Adamaoua", "adamaoua": "Adamaoua", "centre": "Centre", "east": "Est", "est": "Est",
              "farnorth": "Extrême-Nord", "extremenord": "Extrême-Nord", "littoral": "Littoral", "north": "Nord",
              "nord": "Nord", "northwest": "Nord-Ouest", "nordouest": "Nord-Ouest", "west": "Ouest", "ouest": "Ouest",
              "south": "Sud", "sud": "Sud", "southwest": "Sud-Ouest", "sudouest": "Sud-Ouest"}

CATEGORIES = {  # regroupement des libellés hétérogènes des journaux
    "equipementdebatterie": "Système de batterie", "equipementdusystemedebatterie": "Système de batterie",
    "batterie": "Batteries", "equipementderefroidissement": "Refroidissement", "extracteur": "Refroidissement",
    "reseaudedistribution": "Réseau de distribution", "equipementdeconversion": "Conversion (onduleurs, MDU…)",
    "champspv": "Champ PV", "cablepv": "Champ PV", "pvsupport": "Champ PV (structure)", "fondationpv": "Champ PV (structure)",
    "equipementdeprotection": "Protections", "accmcb": "Protections", "courtcircuitdansleshelter": "Protections",
    "capteur": "Capteurs / supervision", "software": "Capteurs / supervision", "compteurdepuissance": "Comptage",
    "netoyage": "Nettoyage", "nettoyage": "Nettoyage", "shortcircuit": "Protections", "filters": "Refroidissement",
    "cablesdecommunication": "Système de batterie", "mc4": "Champ PV", "cable": "Champ PV", "cloture": "Génie civil / clôture",
    "securite": "Génie civil / clôture",
}
# Matériels comptés en longueur (mètres) : exclus des totaux de pièces
MATERIEL_LINEAIRE = {"ligneelectrique", "cablepd", "cablepv", "cable", "cabledecommunication"}

ETATS = {  # état de fonctionnement → classe d'exploitation
    "fonctionnementh24": "Fonctionnelle (H24)", "remiseenmarche": "Fonctionnelle (H24)",
    "apres18h": "Fonctionnement partiel", "arretavant18h": "Fonctionnement partiel", "partielle": "Fonctionnement partiel",
    "programme": "Fonctionnement partiel",
    "enarret": "À l'arrêt", "arretdemarche": "À l'arrêt",
}
CLASSES = ["Fonctionnelle (H24)", "Fonctionnement partiel", "À l'arrêt", "Non renseigné"]


def cle(x) -> str:
    x = unicodedata.normalize("NFKD", str(x)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", x)


def _region(x):
    return REGIONS_FR.get(cle(x), str(x).strip() if pd.notna(x) else None)


def _categorie(x):
    if pd.isna(x) or not str(x).strip():
        return "Non renseignée"
    return CATEGORIES.get(cle(x), str(x).strip()[:1].upper() + str(x).strip()[1:])


def _resultat(x):
    k = cle(x)
    if k.startswith("clo") or k.startswith("cls") or k == "fait":
        return "Clôturé"
    if k.startswith("pend") or k.startswith("enattente"):
        return "En attente"
    return "Non renseigné"


def _priorite(x):
    k = cle(x).upper()
    return k if k in ("CRITICAL", "URGENT", "MAJOR", "MINOR") else "Non renseignée"


def _phase(x):
    m = re.search(r"(\d)", str(x))
    return f"Phase {m.group(1)}" if m else None


def classe_etat(x) -> str:
    return ETATS.get(cle(x), "Non renseigné")


def _annee_fichier(nom: str, dates: pd.Series) -> int:
    m = re.search(r"(20\d\d)", nom or "")
    if m:
        return int(m.group(1))
    d = pd.to_datetime(dates, errors="coerce").dropna()
    return int(d.dt.year.mode().iloc[0]) if len(d) else pd.Timestamp.today().year


def lire_journal(contenu: bytes, nom: str = "") -> dict[str, pd.DataFrame]:
    """Lit un classeur « Maintenance log followup » et renvoie les tableaux normalisés."""
    xls = pd.ExcelFile(io.BytesIO(contenu))
    feuilles = {cle(s): s for s in xls.sheet_names}
    out = {}

    f_def = next((v for k, v in feuilles.items() if k.startswith("touteslesdefauts")), None)
    if f_def is None:
        raise ValueError("feuille « Toutes les Défauts » introuvable : ce n'est pas un journal de maintenance reconnu.")
    brut = pd.read_excel(xls, sheet_name=f_def, header=None)
    ligne_entete = next(i for i in range(min(30, len(brut))) if "Nom du site" in brut.iloc[i].astype(str).tolist())
    d = pd.read_excel(xls, sheet_name=f_def, header=ligne_entete)
    d.columns = [str(c).strip() for c in d.columns]
    d = d.dropna(subset=["Nom du site"])
    d = d[d["Nom du site"].astype(str).str.strip() != ""]
    annee = _annee_fichier(nom, d.get("Date de l'incident"))
    col = lambda *noms: next((d[c] for c in d.columns for n in noms if cle(c) == cle(n)), pd.Series([None] * len(d), index=d.index))
    out["defauts"] = pd.DataFrame({
        "source": f"Journal {annee}",
        "num": pd.to_numeric(col("Numéro de Defaut"), errors="coerce"),
        "site": col("Nom du site").astype(str).str.strip(),
        "id_site": col("ID Site").astype(str).replace({"0": None, "nan": None}),
        "puissance_kwc": pd.to_numeric(col("Modèle"), errors="coerce"),
        "phase": col("Phase").map(_phase),
        "region": col("Région").map(_region),
        "etat_arrivee": col("État du site à l'arrivée").astype(str).str.strip().replace({"nan": "Non renseigné"}),
        "description": col("Description du problème"),
        "materiel": col("Matériel affecté").astype(str).str.strip().replace({"nan": "Non renseigné"}),
        "categorie": col("Catégorie de Défaut").map(_categorie),
        "mesure": col("Mesure prise"),
        "date_incident": pd.to_datetime(col("Date de l'incident"), errors="coerce"),
        "resultat": col("Résultat").map(_resultat),
        "code_materiel": col("Code matériel"),
        "qte_affectee": pd.to_numeric(col("Quantité affectée"), errors="coerce").fillna(0),
        "qte_remplacee": pd.to_numeric(col("Quantité Remplacée"), errors="coerce").fillna(0),
        "priorite": col("Priorité").map(_priorite),
        "jours_prevus": pd.to_numeric(col("Jours prévu"), errors="coerce"),
        "date_achevement": pd.to_datetime(col("date d'achèvement"), errors="coerce"),
        "delai_resolution_j": pd.to_numeric(col("Temps mis pour résoudre (Jour)"), errors="coerce"),
        "commentaire": col("Commentair", "Commentaire"),
    }).reset_index(drop=True)

    f_st = next((v for k, v in feuilles.items() if k.startswith("status")), None)
    if f_st:
        s = pd.read_excel(xls, sheet_name=f_st).dropna(subset=["Nom du site"])
        out["statuts"] = pd.DataFrame({
            "annee": annee, "site": s["Nom du site"].astype(str).str.strip(), "phase": s["Phase"].map(_phase),
            "region": s["Region"].map(_region), "puissance_kwc": pd.to_numeric(s["Model"], errors="coerce"),
            "etat": s["état de fonctionnement"].astype(str).str.strip(),
            "classe": s["état de fonctionnement"].map(classe_etat),
            "causes": s["Causes"].where(s["Causes"].astype(str).str.strip().isin(["0", "nan", ""]) == False),
        })
        f_tp = next((v for k, v in feuilles.items() if k.startswith("tempsdefon")), None)
        if f_tp:
            t = pd.read_excel(xls, sheet_name=f_tp).dropna(subset=["Nom du site"])
            tp = dict(zip(t["Nom du site"].map(cle), t["Temps parametré"]))
            et = dict(zip(t["Nom du site"].map(cle), t["état de fonctionnement"]))
            out["statuts"]["plage_horaire"] = out["statuts"]["site"].map(cle).map(tp)
            out["statuts"]["etat_feuille_temps"] = out["statuts"]["site"].map(cle).map(et)

    f_in = next((v for k, v in feuilles.items() if k.startswith("inspection")), None)
    if f_in:
        i = pd.read_excel(xls, sheet_name=f_in).dropna(subset=["Nom du site"])
        i = i[pd.to_datetime(i["Inspection Date"], errors="coerce").notna()]
        out["inspections"] = pd.DataFrame({
            "annee": annee, "site": i["Nom du site"].astype(str).str.strip(), "phase": i["Phase"].map(_phase),
            "region": i["Region"].map(_region), "date_inspection": pd.to_datetime(i["Inspection Date"], errors="coerce"),
            "inspecte_par": i["Checked-By"].astype(str).str.replace("\n", ", ").replace({"nan": None}),
            "checklist": i["Checklist"], "remarque": i["Remark"]})

    f_rp = next((v for k, v in feuilles.items() if k.startswith("repartition")), None)
    if f_rp:
        r = pd.read_excel(xls, sheet_name=f_rp, header=1).dropna(subset=["Nom du site"])
        out["affectations"] = pd.DataFrame({
            "annee": annee, "site": r["Nom du site"].astype(str).str.strip(),
            "zone": r["Zone"].astype(str).str.upper().str.replace(" ", ""),
            "responsable": r["Responsable"].astype(str).str.strip()})
    return out


def fusionner(existant: pd.DataFrame | None, nouveau: pd.DataFrame, colonne_source: str) -> pd.DataFrame:
    """Remplace les lignes de même source (même année de journal) par les nouvelles."""
    if existant is None or existant.empty:
        return nouveau.reset_index(drop=True)
    sources = set(nouveau[colonne_source].unique())
    return pd.concat([existant[~existant[colonne_source].isin(sources)], nouveau], ignore_index=True)


def normaliser_defauts(d: pd.DataFrame | None) -> pd.DataFrame:
    if d is None or d.empty:
        return pd.DataFrame()
    d = d.copy()
    for c in ("date_incident", "date_achevement"):
        x = pd.to_datetime(d[c], errors="coerce")
        d[c] = x.dt.tz_localize(None) if getattr(x.dt, "tz", None) is not None else x
    for c in ("qte_affectee", "qte_remplacee", "jours_prevus", "delai_resolution_j", "puissance_kwc"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    # Délai de résolution : recalculé à partir des dates quand elles existent ; valeur saisie gardée si plausible.
    calc = (d["date_achevement"] - d["date_incident"]).dt.days
    saisi = d["delai_resolution_j"]
    d["delai_resolution_j"] = calc.where(calc.notna() & (calc >= 0), saisi.where((saisi >= 0) & (saisi <= 1000)))
    d["delai_incoherent"] = (calc < 0) | (saisi < 0) | (saisi > 1000)
    d["etat_arrivee"] = d["etat_arrivee"].fillna("Non renseigné").replace({"nan": "Non renseigné"})
    for c in ("categorie", "priorite", "resultat", "materiel"):
        d[c] = d[c].fillna("Non renseigné" if c != "categorie" else "Non renseignée")
    d["cle_site"] = d["site"].map(cle)
    d["lineaire"] = d["materiel"].map(cle).isin(MATERIEL_LINEAIRE)
    return d


def depuis_saisies(reg: pd.DataFrame) -> pd.DataFrame:
    """Pannes saisies dans l'application, mises au format du journal des défauts."""
    if reg is None or reg.empty:
        return pd.DataFrame()
    p = reg[reg["type"] == "Panne (arrêt)"]
    if p.empty:
        return pd.DataFrame()
    prob = p["problemes"].fillna("").astype(str)
    return pd.DataFrame({
        "source": "Saisie application", "num": p["id"], "site": p["site"], "id_site": None,
        "puissance_kwc": p["puissance_kwc"], "phase": p["phase"], "region": None, "etat_arrivee": "En Arrêt",
        "description": p["observations"], "materiel": prob.str.split("; ").str[0].replace({"": "Non renseigné"}),
        "categorie": prob.str.split("; ").str[0].replace({"": "Non renseignée"}), "mesure": p["actions"],
        "date_incident": p["date_arret"], "resultat": p["statut"].map({"Rétablie": "Clôturé"}).fillna("En attente"),
        "code_materiel": None, "qte_affectee": 0, "qte_remplacee": 0, "priorite": "MAJOR", "jours_prevus": None,
        "date_achevement": p["date_remise"], "delai_resolution_j": p["duree_arret_h"] / 24, "commentaire": p["chef_equipe"]})


def statuts_courants(st_df: pd.DataFrame | None) -> pd.DataFrame:
    """Dernier état connu de chaque centrale (journal le plus récent)."""
    if st_df is None or st_df.empty:
        return pd.DataFrame()
    s = st_df.copy()
    s["cle_site"] = s["site"].map(cle)
    return s.sort_values("annee").groupby("cle_site").tail(1).reset_index(drop=True)


# ------------------------------------------------------------------ indicateurs
def ajouter_calculs(d: pd.DataFrame, aujourd_hui: pd.Timestamp) -> pd.DataFrame:
    d = d.copy()
    ouvert = d["resultat"] != "Clôturé"
    d["age_j"] = ((aujourd_hui - d["date_incident"]).dt.days).where(ouvert)
    d["en_retard"] = ouvert & d["jours_prevus"].notna() & (d["age_j"] > d["jours_prevus"])
    d["dans_les_delais"] = (~ouvert) & d["jours_prevus"].notna() & (d["delai_resolution_j"] <= d["jours_prevus"])
    d["mois"] = d["date_incident"].dt.to_period("M").dt.to_timestamp()
    return d


def kpis(d: pd.DataFrame) -> dict:
    clos = d[d["resultat"] == "Clôturé"]
    avec_delai = clos[clos["jours_prevus"].notna()]
    return {
        "defauts": len(d), "sites": d["cle_site"].nunique(),
        "taux_cloture": len(clos) / len(d) * 100 if len(d) else None,
        "backlog": int((d["resultat"] != "Clôturé").sum()),
        "en_retard": int(d["en_retard"].sum()),
        "mttr_moy": clos["delai_resolution_j"].mean() if len(clos) else None,
        "mttr_med": clos["delai_resolution_j"].median() if len(clos) else None,
        "respect_delais": avec_delai["dans_les_delais"].mean() * 100 if len(avec_delai) else None,
        "arret_arrivee": (d["etat_arrivee"].str.lower().str.contains("arr")).mean() * 100 if len(d) else None,
        "critiques": int(d["priorite"].isin(["CRITICAL", "URGENT"]).sum()),
    }


def pareto(d: pd.DataFrame, col: str, n: int = 15) -> pd.DataFrame:
    p = d[col].fillna("Non renseigné").value_counts().rename_axis(col).reset_index(name="Défauts")
    p["% cumulé"] = (p["Défauts"].cumsum() / p["Défauts"].sum() * 100).round(1)
    return p.head(n)


def par_centrale(d: pd.DataFrame, statuts: pd.DataFrame, affect: pd.DataFrame, aujourd_hui: pd.Timestamp) -> pd.DataFrame:
    if d.empty:
        return pd.DataFrame()
    g = d.groupby("cle_site")
    t = pd.DataFrame({
        "Centrale": g["site"].first(), "Phase": g["phase"].first(), "Région": g["region"].first(),
        "Puissance (kWc)": g["puissance_kwc"].max(),
        "Défauts": g.size(),
        "Critiques": g["priorite"].apply(lambda s: int(s.isin(["CRITICAL", "URGENT"]).sum())),
        "En attente": g["resultat"].apply(lambda s: int((s != "Clôturé").sum())),
        "Arrivées site à l'arrêt": g["etat_arrivee"].apply(lambda s: int(s.str.lower().str.contains("arr").sum())),
        "MTTR (j)": g.apply(lambda x: x.loc[x["resultat"] == "Clôturé", "delai_resolution_j"].mean(), include_groups=False).round(1),
        "Premier défaut": g["date_incident"].min(), "Dernier défaut": g["date_incident"].max(),
        "Catégorie principale": g["categorie"].agg(lambda s: s.value_counts().index[0]),
    })
    jours_inc = g["date_incident"].apply(lambda s: s.dropna().dt.normalize().nunique())
    etendue = (t["Dernier défaut"] - t["Premier défaut"]).dt.days
    t["Jours d'incident distincts"] = jours_inc
    t["MTBF (j)"] = (etendue / (jours_inc - 1)).where(jours_inc > 1).round(0)
    t["Jours depuis le dernier défaut"] = (aujourd_hui - t["Dernier défaut"]).dt.days
    if statuts is not None and not statuts.empty:
        sm = statuts.set_index("cle_site")
        t["État actuel"] = t.index.map(sm["etat"]) if "etat" in sm else None
        t["Causes d'arrêt"] = t.index.map(sm["causes"]) if "causes" in sm else None
    if affect is not None and not affect.empty:
        am = affect.assign(cle_site=affect["site"].map(cle)).drop_duplicates("cle_site").set_index("cle_site")
        t["Zone"] = t.index.map(am["zone"])
        t["Responsable"] = t.index.map(am["responsable"])
    return t.sort_values(["Défauts", "Critiques"], ascending=False).reset_index(drop=True)


def recurrences(d: pd.DataFrame, seuil: int = 2) -> pd.DataFrame:
    r = d.groupby(["site", "materiel"]).agg(Occurrences=("materiel", "size"), Premier=("date_incident", "min"),
                                           Dernier=("date_incident", "max")).reset_index()
    return r[r["Occurrences"] >= seuil].sort_values("Occurrences", ascending=False).rename(
        columns={"site": "Centrale", "materiel": "Matériel"})


def tendance(d: pd.DataFrame) -> pd.DataFrame:
    crees = d.dropna(subset=["mois"]).groupby("mois").size().rename("Défauts déclarés")
    cl = d[d["resultat"] == "Clôturé"].dropna(subset=["date_achevement"])
    clos = cl.groupby(cl["date_achevement"].dt.to_period("M").dt.to_timestamp()).size().rename("Défauts clôturés")
    t = pd.concat([crees, clos], axis=1).fillna(0).sort_index()
    t["Backlog cumulé"] = (t["Défauts déclarés"] - t["Défauts clôturés"]).cumsum()
    return t.reset_index(names="Mois")


def age_backlog(d: pd.DataFrame) -> pd.DataFrame:
    o = d[d["resultat"] != "Clôturé"].dropna(subset=["age_j"])
    tranches = pd.cut(o["age_j"], [-1, 30, 90, 180, 365, 100000],
                      labels=["≤ 30 j", "31–90 j", "91–180 j", "181–365 j", "> 1 an"])
    return pd.crosstab(tranches, o["priorite"]).reset_index(names="Âge")


def pieces(d: pd.DataFrame) -> pd.DataFrame:
    d = d[~d["lineaire"]] if "lineaire" in d else d
    p = d.groupby(["materiel"]).agg(**{"Code": ("code_materiel", lambda s: ", ".join(sorted({str(x) for x in s.dropna()}))[:40]),
                                       "Quantité affectée": ("qte_affectee", "sum"),
                                       "Quantité remplacée": ("qte_remplacee", "sum"),
                                       "Défauts": ("materiel", "size")}).reset_index().rename(columns={"materiel": "Matériel"})
    p["Reste à remplacer"] = (p["Quantité affectée"] - p["Quantité remplacée"]).clip(lower=0)
    p["Taux de remplacement (%)"] = (p["Quantité remplacée"] / p["Quantité affectée"] * 100).where(p["Quantité affectée"] > 0).round(1)
    return p.sort_values("Reste à remplacer", ascending=False)


def par_responsable(d: pd.DataFrame, affect: pd.DataFrame) -> pd.DataFrame:
    if affect is None or affect.empty or d.empty:
        return pd.DataFrame()
    am = affect.assign(cle_site=affect["site"].map(cle)).drop_duplicates("cle_site")
    sites_par_resp = am.groupby(["zone", "responsable"]).size().rename("Sites affectés")
    x = d.merge(am[["cle_site", "zone", "responsable"]], on="cle_site", how="left")
    x["zone"] = x["zone"].fillna("Non affecté")
    x["responsable"] = x["responsable"].fillna("Non affecté")
    x["mttr_tmp"] = x["delai_resolution_j"].where(x["resultat"] == "Clôturé")
    g = x.groupby(["zone", "responsable"]).agg(
        **{"Défauts": ("cle_site", "size"), "Sites avec défauts": ("cle_site", "nunique"),
           "Clôturés": ("resultat", lambda s: int((s == "Clôturé").sum())),
           "En attente": ("resultat", lambda s: int((s != "Clôturé").sum())),
           "En retard": ("en_retard", "sum"),
           "MTTR (j)": ("mttr_tmp", "mean")})
    g["MTTR (j)"] = g["MTTR (j)"].round(1)
    g = g.join(sites_par_resp, how="left")
    g["Taux de clôture (%)"] = (g["Clôturés"] / g["Défauts"] * 100).round(1)
    return g.reset_index().rename(columns={"zone": "Zone", "responsable": "Responsable"})
