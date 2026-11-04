"""
Masse salariale — registre de paie de session + calcul en lot.

Le calcul agent par agent est délégué à `utils/paie_moteur.py` (copie exacte du
moteur `paie_aer.py`, vérifié contre le classeur Calcul_Salaires_AER.xlsx) ; les
montants, taux et options viennent de `data/parametres_paie_aer.json`.

Même principe que les autres registres éditables de l'application : le registre
de paie vit en session (st.session_state), initialisé depuis le registre RH
EFFECTIF (`utils.personnel.get_effective_roster`), complété à l'écran ou par
import, et exportable. Le classeur source n'est jamais modifié.
"""
from __future__ import annotations

import copy
import io
from pathlib import Path

import pandas as pd
import streamlit as st

from .paie_moteur import Agent, calculer_paie, charger_parametres
from .storage import mettre_a_jour, session_ou_stockage

PARAMS_PATH = Path(__file__).resolve().parent.parent / "data" / "parametres_paie_aer.json"
MANQUANT = "— MANQUANT —"

# Colonnes du registre de paie : (colonne affichée, champ du moteur, valeur par défaut)
REGISTRE = [
    ("Matricule", "matricule", ""), ("Nom", "nom", ""), ("Antenne", None, ""), ("Poste RH", None, ""),
    ("Statut", "statut", "Recruté AER"), ("Catégorie", "categorie", None), ("Échelon", "echelon", None),
    ("Palier", "poste", "Aucun"), ("Intérim — palier", "interim_palier", "Aucun"),
    ("Intérim — durée (mois)", "interim_duree_mois", 0), ("Cabinet (astreinte)", "cabinet", "Non"),
    ("Enfants mineurs", "enfants", 0), ("Situation du mois", "situation", "Normal"),
    ("Jours non payés", "jours_non_payes", 0), ("Mois de présence", "mois_presence", 12),
    ("13e mois ce mois", "treizieme_ce_mois", "Non"), ("Prime d'installation ce mois", "installation_ce_mois", "Non"),
    ("Médaille ce mois", "medaille", "Aucune"), ("Gratification exceptionnelle", "gratification", 0),
    ("Autres gains imposables", "autres_gains_imposables", 0), ("Autres gains non imposables", "autres_gains_non_imposables", 0),
    ("Avance sur salaire (retenue)", "avance_retenue", 0), ("Autres retenues", "autres_retenues", 0),
]
COLS_REGISTRE = [c for c, _, _ in REGISTRE]

# Correspondance des en-têtes de l'onglet « Paie » du classeur Calcul_Salaires_AER.xlsx
ENTETES_CLASSEUR = {
    "Matricule": "Matricule", "Nom et prénom": "Nom", "Statut": "Statut", "Catégorie (1-12)": "Catégorie",
    "Échelon (A-G)": "Échelon", "Poste (palier)": "Palier", "Intérim : palier": "Intérim — palier",
    "Intérim : durée (mois)": "Intérim — durée (mois)", "Cabinet PCA/DG/DGA (astreinte)": "Cabinet (astreinte)",
    "Enfants mineurs": "Enfants mineurs", "Situation du mois": "Situation du mois", "Jours non payés": "Jours non payés",
    "Mois de présence dans l'année": "Mois de présence", "13e mois ce mois ?": "13e mois ce mois",
    "Prime d'installation ce mois ?": "Prime d'installation ce mois", "Médaille ce mois": "Médaille ce mois",
    "Gratification exceptionnelle": "Gratification exceptionnelle", "Autres gains imposables": "Autres gains imposables",
    "Autres gains non imposables": "Autres gains non imposables",
    "Avance sur salaire : retenue du mois": "Avance sur salaire (retenue)", "Autres retenues": "Autres retenues",
}

# Résultats affichés : (clé du moteur, libellé)
RESULTATS = [
    ("groupe", "Groupe"), ("palier_effectif", "Palier effectif"), ("salaire_base", "Salaire de base"),
    ("ind_logement", "Ind. logement"), ("ind_deplacement", "Ind. déplacement"), ("prime_technicite", "Prime technicité"),
    ("prime_sujetion", "Prime sujétion"), ("prime_representation", "Prime représentation"),
    ("allocation_familiale", "Allocation familiale"), ("prime_fonction", "Prime fonction"), ("prime_astreinte", "Prime astreinte"),
    ("dotation_carburant", "Carburant (paie)"), ("credit_communication", "Communication (paie)"),
    ("treizieme_mois", "13e mois"), ("prime_installation", "Prime installation"), ("medaille", "Médaille"),
    ("brut_total", "Brut"), ("brut_soumis_cnps", "Brut soumis CNPS"), ("brut_imposable", "Brut imposable"),
    ("cnps_salarie", "CNPS salarié"),
    ("cfc_salarie", "CFC salarié"), ("irpp", "IRPP"), ("cac", "CAC"), ("rav", "RAV"), ("tdl", "TDL"),
    ("total_retenues", "Total retenues"), ("net_a_payer", "Net à payer"),
    ("patronal_pvid", "CNPS vieillesse (patronal)"), ("patronal_af", "Prestations familiales (patronal)"),
    ("patronal_at", "Accidents du travail (patronal)"), ("patronal_cfc_pat", "CFC patronal"), ("patronal_fne", "FNE patronal"),
    ("total_charges_patronales", "Charges patronales"), ("cout_employeur", "Coût employeur"),
]
MONTANTS = [lib for k, lib in RESULTATS if k not in ("groupe", "palier_effectif")]
ELEMENTS_GAINS = ["Salaire de base", "Ind. logement", "Ind. déplacement", "Prime technicité", "Prime sujétion",
                  "Prime représentation", "Allocation familiale", "Prime fonction", "Prime astreinte",
                  "Carburant (paie)", "Communication (paie)", "13e mois", "Prime installation", "Médaille"]


@st.cache_data(show_spinner=False)
def parametres_par_defaut() -> dict:
    return charger_parametres(str(PARAMS_PATH))


def parametres_session() -> dict:
    """Copie de session des paramètres, modifiable depuis la page sans toucher au JSON."""
    if "paie_params" not in st.session_state:
        st.session_state["paie_params"] = copy.deepcopy(parametres_par_defaut())
    return st.session_state["paie_params"]


def reinitialiser_parametres() -> None:
    st.session_state.pop("paie_params", None)


def _registre_vide(n: int = 0) -> pd.DataFrame:
    return pd.DataFrame({c: [d] * n for c, _, d in REGISTRE}, columns=COLS_REGISTRE)


def registre_depuis_personnel(equipes_rows: pd.DataFrame | None, unassigned: pd.DataFrame | None) -> pd.DataFrame:
    """Pré-remplit un registre de paie avec les agents du registre RH effectif
    (équipes, hors postes vacants, + pool non affecté). Catégorie et échelon
    restent à saisir : le classeur RH ne les contient pas."""
    lignes = []
    if equipes_rows is not None and not equipes_rows.empty:
        occ = equipes_rows[equipes_rows["Nom"].astype(str).str.strip() != MANQUANT]
        for _, r in occ.iterrows():
            lignes.append({"Nom": r.get("Nom"), "Antenne": r.get("Antenne"),
                           "Poste RH": r.get("Poste (fichier RH)") or r.get("Rôle")})
    if unassigned is not None and not unassigned.empty:
        for _, r in unassigned.iterrows():
            lignes.append({"Nom": r.get("Nom"), "Antenne": "Non affecté",
                           "Poste RH": r.get("Poste (fichier RH)") or r.get("Profil")})
    reg = _registre_vide(len(lignes))
    for i, l in enumerate(lignes):
        for k, v in l.items():
            reg.at[i, k] = v
        reg.at[i, "Matricule"] = f"AER-{i + 1:04d}"
    return reg


def lire_import(fichier) -> pd.DataFrame:
    """Lit un registre importé : onglet « Paie » du classeur Calcul_Salaires_AER.xlsx
    (en-têtes en ligne 5), ou tout CSV / Excel portant les colonnes du registre."""
    nom = getattr(fichier, "name", "").lower()
    if nom.endswith(".csv"):
        df = pd.read_csv(fichier)
    else:
        xls = pd.ExcelFile(fichier)
        if "Paie" in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name="Paie", header=4)
            df = df.rename(columns=ENTETES_CLASSEUR)
            df = df[df.get("Catégorie").notna()] if "Catégorie" in df.columns else df
        else:
            df = pd.read_excel(xls, sheet_name=0)
    reg = _registre_vide(len(df))
    for c in COLS_REGISTRE:
        if c in df.columns:
            reg[c] = df[c].values
    return normaliser(reg)


def normaliser(reg: pd.DataFrame) -> pd.DataFrame:
    reg = reg.copy()
    for c, _, d in REGISTRE:
        if c not in reg.columns:
            reg[c] = d
        if d is not None and c not in ("Matricule", "Nom", "Antenne", "Poste RH"):
            reg[c] = reg[c].where(reg[c].notna() & (reg[c].astype(str).str.strip() != ""), d)
    reg["Catégorie"] = pd.to_numeric(reg["Catégorie"], errors="coerce").astype("Int64")
    reg["Échelon"] = reg["Échelon"].astype("string").str.strip().str.upper()
    return reg[COLS_REGISTRE]


def get_registre(equipes_rows, unassigned) -> pd.DataFrame:
    reg = session_ou_stockage("paie_registre", lambda: registre_depuis_personnel(equipes_rows, unassigned))
    return normaliser(reg)


def set_registre(reg: pd.DataFrame) -> None:
    mettre_a_jour("paie_registre", normaliser(reg))
    # nouvelle clé d'éditeur : évite de ré-appliquer d'anciennes modifications sur un nouveau registre
    st.session_state["paie_ver"] = st.session_state.get("paie_ver", 0) + 1
    # nouvelle clé d'éditeur : évite de ré-appliquer d'anciennes modifications sur un nouveau registre
    st.session_state["paie_ver"] = st.session_state.get("paie_ver", 0) + 1


def _agent(row: pd.Series) -> Agent:
    kw = {}
    for col, champ, d in REGISTRE:
        if champ is None:
            continue
        v = row.get(col, d)
        if pd.isna(v) if not isinstance(v, str) else False:
            v = d
        if champ == "categorie":
            v = int(v)
        elif champ in ("enfants",):
            v = int(float(v))
        elif champ in ("interim_duree_mois", "jours_non_payes", "mois_presence", "gratification",
                       "autres_gains_imposables", "autres_gains_non_imposables", "avance_retenue", "autres_retenues"):
            v = float(v)
        else:
            v = str(v)
        kw[champ] = v
    return Agent(**kw)


def valider(row: pd.Series, P: dict) -> str | None:
    """Renvoie un motif d'exclusion, ou None si la ligne est calculable."""
    cat, ech = row.get("Catégorie"), row.get("Échelon")
    if pd.isna(cat) or not 1 <= int(cat) <= 12:
        return "Catégorie manquante ou hors 1-12"
    if pd.isna(ech) or str(ech) not in P["ECHELONS"]:
        return "Échelon manquant ou hors A-G"
    for col, liste in (("Statut", P["STATUTS"]), ("Situation du mois", P["SITUATIONS"]),
                       ("Palier", P["PALIERS"]), ("Intérim — palier", P["PALIERS"])):
        if str(row.get(col)) not in liste:
            return f"{col} inconnu : {row.get(col)}"
    if str(row.get("Médaille ce mois")) not in ("Aucune", "Argent", "Vermeil", "Or"):
        return "Médaille inconnue"
    return None


def calculer_masse(reg: pd.DataFrame, P: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Renvoie (résultats calculés, lignes exclues avec motif)."""
    ok, exclus = [], []
    for _, row in reg.iterrows():
        motif = valider(row, P)
        if motif:
            exclus.append({"Matricule": row.get("Matricule"), "Nom": row.get("Nom"), "Motif": motif})
            continue
        r = calculer_paie(_agent(row), P)
        ligne = {c: row.get(c) for c in ("Matricule", "Nom", "Antenne", "Poste RH", "Statut", "Catégorie",
                                         "Échelon", "Palier", "Situation du mois")}
        ligne.update({lib: (round(r[k], 0) if isinstance(r[k], float) else r[k]) for k, lib in RESULTATS})
        ok.append(ligne)
    res = pd.DataFrame(ok)
    if not res.empty:
        res["Catégorie"] = res["Catégorie"].astype(int)
        res["Groupe"] = res["Groupe"].map({1: "G1 (cat. 1-6)", 2: "G2 (cat. 7-9)", 3: "G3 (cat. 10-12)"})
    return res, pd.DataFrame(exclus, columns=["Matricule", "Nom", "Motif"])


def ventiler(res: pd.DataFrame, dimension: str) -> pd.DataFrame:
    g = res.groupby(dimension, dropna=False)
    out = g.agg(Effectif=("Nom", "size"), Brut=("Brut", "sum"), Net=("Net à payer", "sum"),
                Retenues=("Total retenues", "sum"), **{"Charges patronales": ("Charges patronales", "sum")},
                **{"Coût employeur": ("Coût employeur", "sum")}, **{"Brut moyen": ("Brut", "mean")}).reset_index()
    total = out["Coût employeur"].sum()
    out["Part du coût (%)"] = (out["Coût employeur"] / total * 100).round(1) if total else 0.0
    out["Brut moyen"] = out["Brut moyen"].round(0)
    return out


def vers_excel(feuilles: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for nom, df in feuilles.items():
            df.to_excel(xw, sheet_name=nom[:31], index=False)
    return buf.getvalue()


# ============================================================== Simulation de recrutement
PROFILS_COLS = ["Profil / poste", "Nombre", "Antenne", "Statut", "Catégorie", "Échelon", "Palier",
                "Enfants mineurs", "Date d'embauche", "Durée d'essai (mois)", "Essai renouvelé"]


def duree_essai_statutaire(categorie: int, statut: str) -> float:
    """[Art. 6] Durée d'essai en mois selon la catégorie ; les fonctionnaires détachés et
    agents de l'État mis à disposition en sont exempts."""
    if statut in ("Fonctionnaire détaché", "Agent de l'État mis à disposition"):
        return 0.0
    c = int(categorie)
    return 0.5 if c <= 2 else 1.0 if c <= 4 else 2.0 if c <= 6 else 3.0 if c <= 9 else 4.0


def profils_exemple(debut) -> pd.DataFrame:
    d = pd.Timestamp(debut).normalize().replace(day=1)
    lignes = [
        ("Ingénieur", 2, "", "Recruté AER", 10, "A", "Aucun", 0, d, None, "Non"),
        ("Technicien", 3, "", "Recruté AER", 7, "A", "Aucun", 0, d, None, "Non"),
        ("Chauffeur", 2, "", "Recruté AER", 3, "A", "Aucun", 0, d + pd.DateOffset(months=2), None, "Non"),
    ]
    return pd.DataFrame(lignes, columns=PROFILS_COLS)


def _mois(debut, fin) -> pd.PeriodIndex:
    return pd.period_range(pd.Timestamp(debut).to_period("M"), pd.Timestamp(fin).to_period("M"), freq="M")


def simuler_recrutement(profils: pd.DataFrame, debut, fin, P: dict, avancement: bool = False
                        ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Coût mensuel du personnel à recruter sur la période [debut, fin].

    Règles :
      - aucun coût avant le mois d'embauche ; l'embauche est réputée au 1er du mois ;
      - pendant l'essai (durée saisie, ou durée statutaire de l'art. 6 si vide ; doublée si
        l'essai est renouvelé) : salaire de base seul ; ensuite, salaire de base + indemnités ;
      - un mois partiellement en essai est proratisé (ex. essai de 0,5 mois) ;
      - option : avancement d'échelon de droit tous les 24 mois [art. 10 b], plafonné à G.
    Renvoie (détail mensuel par profil, profils exclus avec motif)."""
    mois = _mois(debut, fin)
    lignes, exclus = [], []
    montants = ["Brut", "Retenues", "Net à payer", "Charges patronales", "Coût employeur"]
    for i, p in profils.reset_index(drop=True).iterrows():
        nom = str(p.get("Profil / poste") or f"Profil {i + 1}")
        try:
            n = int(float(p.get("Nombre") or 0))
            cat = int(p.get("Catégorie"))
            ech0 = str(p.get("Échelon") or "A").strip().upper()
            statut = str(p.get("Statut") or "Recruté AER")
            palier = str(p.get("Palier") or "Aucun")
            enfants = int(float(p.get("Enfants mineurs") or 0))
            embauche = pd.Timestamp(p.get("Date d'embauche")).to_period("M")
            assert 1 <= cat <= 12 and ech0 in P["ECHELONS"] and statut in P["STATUTS"] and palier in P["PALIERS"]
        except Exception:  # noqa: BLE001
            exclus.append({"Profil / poste": nom, "Motif": "Nombre, catégorie, échelon, statut, palier ou date d'embauche invalide"})
            continue
        if n <= 0:
            exclus.append({"Profil / poste": nom, "Motif": "Nombre nul"})
            continue
        essai = p.get("Durée d'essai (mois)")
        essai = duree_essai_statutaire(cat, statut) if essai is None or pd.isna(essai) else float(essai)
        if str(p.get("Essai renouvelé")) == "Oui":
            essai *= 2
        for m in mois:
            k = (m - embauche).n  # mois écoulés depuis l'embauche
            if k < 0:
                continue
            ech = ech0
            if avancement:
                ech = P["ECHELONS"][min(P["ECHELONS"].index(ech0) + k // 24, len(P["ECHELONS"]) - 1)]
            part_essai = min(max(essai - k, 0.0), 1.0)
            base_agent = dict(categorie=cat, echelon=ech, statut=statut, poste=palier, enfants=enfants)
            plein = calculer_paie(Agent(**base_agent), P)
            essai_r = calculer_paie(Agent(**base_agent, en_essai="Oui"), P) if part_essai > 0 else plein
            def mix(cle):
                return n * (part_essai * essai_r[cle] + (1 - part_essai) * plein[cle])
            lignes.append({
                "Mois": m.to_timestamp(), "Profil / poste": nom, "Antenne": p.get("Antenne") or "",
                "Catégorie": cat, "Échelon": ech, "Palier": palier, "Effectif": n,
                "Phase": "Essai" if part_essai == 1 else ("Après essai" if part_essai == 0 else "Fin d'essai (mois partiel)"),
                "Salaire de base": n * plein["salaire_base"],
                "Indemnités et primes": mix("brut_total") - n * plein["salaire_base"],
                "Brut": mix("brut_total"), "Retenues": mix("total_retenues"), "Net à payer": mix("net_a_payer"),
                "Charges patronales": mix("total_charges_patronales"), "Coût employeur": mix("cout_employeur"),
                "Coût en essai": n * part_essai * essai_r["cout_employeur"],
                "Coût après essai": n * (1 - part_essai) * plein["cout_employeur"],
            })
    det = pd.DataFrame(lignes)
    if not det.empty:
        for c in montants + ["Salaire de base", "Indemnités et primes", "Coût en essai", "Coût après essai"]:
            det[c] = det[c].round(0)
    return det, pd.DataFrame(exclus, columns=["Profil / poste", "Motif"])
