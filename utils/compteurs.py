"""Données et logique de la page « Statistiques des compteurs ».

Important — comme pour le Fonds revolving (voir `utils/revolving.py`), le
classeur Excel du tableau de bord AER (Gestion_Parc_Solaire...) ne contient
AUCUNE donnée sur les compteurs/abonnés installés : cette page lit ses
propres fichiers, déposés indépendamment par l'utilisateur dans la barre
latérale, et les garde en mémoire de session (comme le registre du Fonds
revolving) le temps de la session.

Deux formats de fichier sont pris en charge :

1. **Export Holley** (le format réel des fichiers fournis par l'AER — export
   du système de gestion des compteurs prépayés « Holley ») : détecté
   automatiquement par la présence des colonnes `Full Address` / `Template
   Code`. Particularité importante, constatée sur les fichiers d'exemple :
   la colonne `Opening Date` de ces exports est un champ système toujours
   égal à 01/01/2018 — elle n'indique donc PAS la vraie date d'installation.
   Chaque fichier correspond en réalité à un **lot d'abonnés** exporté à une
   date donnée (le nom du fichier est lui-même une date, ex.
   « 01-10-2024.xls ») : c'est CETTE date de lot qui sert de période
   d'installation pour toutes ses lignes — convention confirmée par l'AER.

2. **Format générique** (si les colonnes ci-dessus sont absentes) : on
   retombe sur une correspondance manuelle des colonnes, l'utilisateur
   indiquant lui-même quelle colonne est la localité / la date.

Attention au vocabulaire (confirmé par l'AER) : la colonne `Holley System ID`
des exports (ex. « 31K433 ») est un **poste** — l'équipement/poste de
configuration Holley ayant servi à enregistrer les compteurs — PAS le site au
sens du reste de l'application. Le vrai « site » (au sens du tableau de bord
parc solaire) correspond ici à la **localité** : c'est pour cela que
`suggest_locality_groups` la rapproche des 499 sites officiels du parc
solaire. Un même poste peut couvrir plusieurs localités/sites, et c'est donc
`localite` (pas `poste`) qui doit être lue comme « site » partout dans
l'interface.

Les données réelles contiennent aussi beaucoup de variantes d'orthographe sur
les noms de localités (ex. « DJIGBAMAFOU » / « DJIGBAMAFOUS », ou des
coquilles comme « DOUKOUR0Y » pour « DOUKOUROY ») : `suggest_locality_groups`
propose un regroupement automatique (par similarité de texte) que
l'utilisateur valide ou corrige avant de lancer les statistiques — rien
n'est fusionné silencieusement, dans le même esprit de rigueur des données
que le reste de l'application (voir la carte d'électrification et le Fonds
revolving)."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Phases du projet (plages de dates éditables, définies par l'utilisateur —
# aucune colonne « phase » n'existe dans les exports Holley)
# ---------------------------------------------------------------------------
def default_phases(df: pd.DataFrame) -> pd.DataFrame:
    """Point de départ pour le tableau éditable des phases (barre latérale) :
    3 phases nommées « Phase I/II/III » couvrant, à parts égales, toute la
    période observée dans `df` — à corriger avec les vraies dates de chaque
    phase du projet (ce module n'a aucune connaissance de ces dates)."""
    noms = ["Phase I", "Phase II", "Phase III"]
    if df.empty or "periode" not in df.columns or df["periode"].isna().all():
        return pd.DataFrame({"Phase": noms, "Début": [None] * 3, "Fin": [None] * 3})
    debut_total, fin_total = df["periode"].min().date(), df["periode"].max().date()
    if debut_total == fin_total:
        return pd.DataFrame({"Phase": noms, "Début": [debut_total] * 3, "Fin": [fin_total] * 3})
    jours = (fin_total - debut_total).days
    bornes = [debut_total,
              debut_total + timedelta(days=jours // 3),
              debut_total + timedelta(days=2 * jours // 3),
              fin_total]
    return pd.DataFrame({
        "Phase": noms,
        "Début": [bornes[0], bornes[1], bornes[2]],
        "Fin": [bornes[1], bornes[2], bornes[3]],
    })


def assign_phases(df: pd.DataFrame, phases: pd.DataFrame) -> pd.Series:
    """Classe chaque ligne de `df` dans une phase, à partir de son `periode`
    et du tableau `phases` (colonnes Phase / Début / Fin — dates incluses aux
    deux bornes, éditées par l'utilisateur dans la barre latérale). Les
    plages sont testées dans l'ordre du tableau ; en cas de chevauchement,
    la première phase qui correspond l'emporte. Une ligne dont la période ne
    tombe dans aucune plage définie reçoit '(hors phase)' — jamais fusionnée
    silencieusement dans une phase voisine."""
    resultat = pd.Series("(hors phase)", index=df.index, dtype="object")
    non_classees = pd.Series(True, index=df.index)
    dates_installation = df["periode"].dt.date
    for _, ligne in phases.iterrows():
        nom, debut, fin = ligne.get("Phase"), ligne.get("Début"), ligne.get("Fin")
        if pd.isna(nom) or not str(nom).strip() or pd.isna(debut) or pd.isna(fin):
            continue
        masque = non_classees & (dates_installation >= debut) & (dates_installation <= fin)
        resultat[masque] = str(nom).strip()
        non_classees &= ~masque
    return resultat


# ---------------------------------------------------------------------------
# Format Holley (format réel des fichiers fournis par l'AER)
# ---------------------------------------------------------------------------
COLONNES_HOLLEY_ATTENDUES = {"Full Address", "Template Code"}


def est_format_holley(raw: pd.DataFrame) -> bool:
    return COLONNES_HOLLEY_ATTENDUES.issubset(set(raw.columns))


def read_excel_sheet_names(uploaded_file) -> list[str]:
    try:
        return pd.ExcelFile(uploaded_file).sheet_names
    except Exception:  # noqa: BLE001
        return []


def load_excel(uploaded_file, sheet_name=0) -> pd.DataFrame:
    return pd.read_excel(uploaded_file, sheet_name=sheet_name)


_MOTIF_DATE_NOM_FICHIER = re.compile(r"(\d{1,2})[-_](\d{1,2})[-_](\d{4})")


def parse_date_from_filename(nom_fichier: str, jour_mois_annee: bool = True) -> date | None:
    """Extrait la date de lot encodée dans le nom du fichier (ex.
    « 01-10-2024.xls »). `jour_mois_annee=True` suppose le format JJ-MM-AAAA
    (convention camerounaise/française) ; sinon MM-JJ-AAAA."""
    m = _MOTIF_DATE_NOM_FICHIER.search(nom_fichier)
    if not m:
        return None
    a, b, annee = int(m.group(1)), int(m.group(2)), int(m.group(3))
    jour, mois = (a, b) if jour_mois_annee else (b, a)
    try:
        return date(annee, mois, jour)
    except ValueError:
        try:  # au cas où l'hypothèse jour/mois serait inversée pour CE fichier précis
            return date(annee, jour, mois)
        except ValueError:
            return None


_MOTIF_MOT_DOUBLE = re.compile(r"^(.+?) \1$")


def _normaliser_localite(brut) -> str:
    """Nettoyage léger avant le regroupement par similarité : espaces
    multiples, et le cas fréquent d'un nom de localité dupliqué deux fois
    de suite (« DJIGBAMAFOUS DJIGBAMAFOUS »), que la seule similarité de
    texte ne détecte pas bien (la répétition fait baisser le score de
    ressemblance avec la version simple).

    `brut` peut être une vraie valeur manquante (None/NaN/pd.NA) : avec les
    versions récentes de pandas (dtype "str" par défaut), une cellule Excel
    vide reste une valeur manquante même après `.astype(str)` — elle n'est
    PAS convertie en texte "nan" comme avec l'ancien dtype "object". Sans
    cette garde, `re.sub` reçoit un float et lève un TypeError (observé en
    production sur un fichier contenant une adresse vide)."""
    if pd.isna(brut):
        return "(localité non renseignée)"
    s = re.sub(r"\s+", " ", str(brut)).strip()
    m = _MOTIF_MOT_DOUBLE.match(s)
    return m.group(1) if m else s


def build_from_holley_files(fichiers: list[dict]) -> pd.DataFrame:
    """`fichiers` = [{"nom": str, "df": DataFrame brut, "periode": date}, ...]
    Renvoie un DataFrame normalisé, une ligne par compteur/abonné."""
    blocs = []
    for f in fichiers:
        raw, n = f["df"], len(f["df"])
        bloc = pd.DataFrame()
        bloc["localite_brute"] = (raw.get("Full Address", pd.Series(["(non renseigné)"] * n)).astype(str)
                                   .str.strip().str.upper().map(_normaliser_localite))
        # "Holley System ID" est un POSTE (équipement/poste de configuration Holley),
        # pas un site au sens du reste de l'application — voir docstring du module.
        bloc["poste"] = (raw.get("Holley System ID", pd.Series(["(non renseigné)"] * n)).astype(str)
                         .str.strip().fillna("(non renseigné)"))
        template = raw.get("Template Code", pd.Series(["(non renseigné)"] * n)).astype(str)
        parties = template.str.split("|", n=1, expand=True)
        # .fillna ici est important : sans elle, une cellule manquante resterait une vraie
        # valeur manquante (pandas >= 3.0) et serait silencieusement exclue des agrégations
        # (groupby/value_counts ignorent les NaN par défaut) — faussant les répartitions par
        # rapport au total réel de compteurs installés.
        bloc["categorie"] = (parties[0].str.strip().fillna("(non renseigné)") if 0 in parties
                              else "(non renseigné)")
        bloc["type_compteur"] = (parties[1].str.strip().str.upper().fillna("(non renseigné)")
                                  if parties.shape[1] > 1 and 1 in parties else "(non renseigné)")
        bloc["solaire"] = bloc["type_compteur"].str.contains("SOLAR|SOLAIRE", regex=True, na=False)
        bloc["numero_compteur"] = raw.get("Old Consumer No.", raw.get("Holley Meter ID", pd.Series(range(n))))
        bloc["periode"] = pd.Timestamp(f["periode"]).to_period("M").to_timestamp()
        bloc["nom_fichier"] = f["nom"]
        blocs.append(bloc)
    out = pd.concat(blocs, ignore_index=True)
    out.loc[out["localite_brute"].isin(["0", "", "NAN", "NONE"]), "localite_brute"] = "(localité non renseignée)"
    out["localite"] = out["localite_brute"]  # remplacé par la version nettoyée une fois validée par l'utilisateur
    return out


_CHEMIN_SITES_OFFICIELS = Path(__file__).resolve().parent.parent / "data" / "sites_officiels_aer.csv"


@st.cache_data(show_spinner=False)
def load_official_sites() -> pd.DataFrame:
    """Liste officielle des 499 sites du parc solaire AER (colonnes nom /
    région / département / antenne), extraite du classeur
    `Gestion_Parc_Solaire_AER2027_DASHBOARD.xlsx` (feuille « Données
    sites ») et embarquée dans ce dépôt comme référence — pas une donnée
    compteurs : elle sert uniquement à retrouver l'orthographe officielle
    d'une localité quand un compteur y a été installé. Beaucoup de
    localités des exports Holley ne correspondent à aucun site de cette
    liste (sous-localités, quartiers) : c'est normal, ces localités restent
    gérées par le regroupement interne ci-dessous."""
    if _CHEMIN_SITES_OFFICIELS.exists():
        return pd.read_csv(_CHEMIN_SITES_OFFICIELS)
    return pd.DataFrame(columns=["nom", "region", "departement", "antenne"])


def suggest_locality_groups(
    localites_brutes: list[str], seuil: float = 0.82,
    sites_officiels: list[str] | None = None, seuil_officiel: float = 0.80,
) -> tuple[dict[str, str], dict[str, str]]:
    """Propose une correction pour chaque localité brute, en deux passes :

    1. **Rapprochement d'un site officiel AER** (si `sites_officiels` est
       fourni) : si une localité ressemble fortement (similarité de texte
       >= `seuil_officiel`) à un des 499 sites du parc solaire, elle est
       corrigée vers l'orthographe officielle de ce site.
    2. **Regroupement interne** (comme avant) pour les localités restantes :
       les variantes très similaires entre elles (coquilles, casse,
       espaces) sont regroupées sous la variante la plus fréquente.

    Ne fusionne JAMAIS automatiquement deux noms franchement différents, et
    ne fait JAMAIS correspondre une localité à un site officiel sans un
    score de similarité élevé : c'est une suggestion à valider dans
    l'interface, pas une correction silencieuse. Renvoie `(mapping, source)`
    où `source[nom_brut]` vaut "Site officiel AER", "Regroupement interne"
    ou "Inchangé"."""
    comptes = pd.Series(localites_brutes).value_counts()
    noms = list(comptes.index)
    mapping: dict[str, str] = {}
    source: dict[str, str] = {}
    deja_groupes: set[str] = set()

    lookup_officiel: dict[str, str] = {}
    noms_officiels_maj: list[str] = []
    if sites_officiels:
        for s in sites_officiels:
            maj = str(s).strip().upper()
            if maj and maj not in lookup_officiel:
                lookup_officiel[maj] = str(s).strip()
        noms_officiels_maj = list(lookup_officiel.keys())

    restants = []
    for nom in noms:
        if nom == "(localité non renseignée)":
            mapping[nom] = nom
            source[nom] = "—"
            deja_groupes.add(nom)
            continue
        if noms_officiels_maj:
            meilleur = max(noms_officiels_maj, key=lambda o: difflib.SequenceMatcher(None, nom, o).ratio())
            ratio = difflib.SequenceMatcher(None, nom, meilleur).ratio()
            if ratio >= seuil_officiel:
                mapping[nom] = lookup_officiel[meilleur]
                source[nom] = "Site officiel AER"
                deja_groupes.add(nom)
                continue
        restants.append(nom)

    for nom in restants:
        if nom in deja_groupes:
            continue
        groupe = [nom]
        for autre in restants:
            if autre == nom or autre in deja_groupes:
                continue
            if difflib.SequenceMatcher(None, nom, autre).ratio() >= seuil:
                groupe.append(autre)
        if len(groupe) > 1:
            canonique = max(groupe, key=lambda g: comptes[g])
            for g in groupe:
                mapping[g] = canonique
                source[g] = "Regroupement interne"
                deja_groupes.add(g)
        else:
            mapping[nom] = nom
            source[nom] = "Inchangé"
            deja_groupes.add(nom)
    return mapping, source


def apply_locality_mapping(df: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    df = df.copy()
    df["localite"] = df["localite_brute"].map(mapping).fillna(df["localite_brute"])
    return df


def locality_cleanup_ui(df: pd.DataFrame) -> pd.DataFrame:
    """Tableau éditable (barre latérale) proposant une correction pour
    chaque localité brute détectée — vers un site officiel AER quand la
    ressemblance est forte, sinon un regroupement interne des variantes
    d'orthographe ; renvoie `df` avec sa colonne `localite` mise à jour
    selon les corrections validées par l'utilisateur. Rien n'est fusionné
    sans validation."""
    comptes = df["localite_brute"].value_counts()
    sites_ref = load_official_sites()
    noms_officiels = sites_ref["nom"].tolist() if not sites_ref.empty else None
    suggestion, source = suggest_locality_groups(df["localite_brute"].tolist(), sites_officiels=noms_officiels)
    table_initiale = pd.DataFrame({
        "Localité (brute)": comptes.index,
        "Occurrences": comptes.values,
        "Localité retenue": [suggestion.get(n, n) for n in comptes.index],
        "Origine de la correction": [source.get(n, "—") for n in comptes.index],
    })
    cle = "cpt_localite_cleanup_" + str(abs(hash(tuple(sorted(comptes.index)))))
    with st.sidebar.expander(f"🧹 Vérifier les localités ({len(comptes)} valeurs brutes)", expanded=False):
        st.caption(
            "Les fichiers réels contiennent souvent des variantes d'orthographe pour une même "
            "localité (coquilles, casse, espaces). Une proposition est déjà pré-remplie ci-dessous : "
            "« Site officiel AER » quand la localité ressemble fortement à un des 499 sites du parc "
            "solaire (orthographe officielle reprise), « Regroupement interne » pour les variantes "
            "d'une même localité regroupées entre elles. Corrige la colonne « Localité retenue » si "
            "besoin — rien n'est fusionné sans validation."
        )
        edite = st.data_editor(
            table_initiale, hide_index=True, width="stretch", key=cle,
            disabled=["Localité (brute)", "Occurrences", "Origine de la correction"],
            height=min(60 + 36 * len(table_initiale), 400),
        )
    mapping = dict(zip(edite["Localité (brute)"], edite["Localité retenue"]))
    return apply_locality_mapping(df, mapping)


# ---------------------------------------------------------------------------
# Format générique (correspondance manuelle des colonnes)
# ---------------------------------------------------------------------------
def apply_column_mapping(raw: pd.DataFrame, mapping: dict) -> tuple[pd.DataFrame, int]:
    """mapping = {"localite": "<nom de colonne réel>", "date_installation": "...",
    "poste": "..." | None, "type_compteur": "..." | None}."""
    out = pd.DataFrame()
    out["localite_brute"] = raw[mapping["localite"]].astype(str).str.strip().str.upper().map(_normaliser_localite)
    out["date_installation"] = pd.to_datetime(raw[mapping["date_installation"]], errors="coerce")
    out["poste"] = (raw[mapping["poste"]].astype(str).str.strip().fillna("(non précisé)")
                    if mapping.get("poste") else "(non précisé)")
    out["type_compteur"] = (raw[mapping["type_compteur"]].astype(str).str.strip().str.upper().fillna("(non précisé)")
                             if mapping.get("type_compteur") else "(non précisé)")
    out["solaire"] = out["type_compteur"].str.contains("SOLAR|SOLAIRE", regex=True, na=False)
    out["localite"] = out["localite_brute"]
    out["nom_fichier"] = "(fichier unique)"
    n_avant = len(out)
    out = out.dropna(subset=["date_installation"])
    out["periode"] = out["date_installation"].dt.to_period("M").dt.to_timestamp()
    n_rejetees = n_avant - len(out)
    return out, n_rejetees


# ---------------------------------------------------------------------------
# Traçabilité des lots — un fichier Holley = un lot d'abonnés exporté à une
# date donnée (voir docstring du module). Permet de vérifier, lot par lot,
# que la période détectée depuis le nom de fichier est cohérente.
# ---------------------------------------------------------------------------
def lot_summary(df: pd.DataFrame) -> pd.DataFrame:
    if "nom_fichier" not in df.columns:
        return pd.DataFrame()
    g = df.groupby("nom_fichier", dropna=False)
    out = g.agg(
        Compteurs=("nom_fichier", "size"),
        Période=("periode", "max"),
        Localités=("localite", "nunique"),
    )
    if "solaire" in df.columns:
        out["Compteurs solaires"] = g["solaire"].sum().astype(int)
    out = out.reset_index().rename(columns={"nom_fichier": "Fichier (lot)"})
    return out.sort_values("Période")


# ---------------------------------------------------------------------------
# Cache de session pour la page d'accueil — la page « Statistiques des
# compteurs » recalcule son tableau `df` à chaque exécution à partir des
# fichiers déposés (aucune donnée persistante entre deux sessions, voir la
# docstring du module). Pour que la page d'accueil puisse en afficher un
# résumé SANS réimplémenter toute la logique de lecture/nettoyage, la page
# des compteurs dépose ici une copie du tableau final (après nettoyage des
# localités et classement par phase) ; tant qu'aucun fichier n'a été déposé
# cette session, le cache reste vide et la page d'accueil l'indique
# explicitement plutôt que d'inventer un chiffre.
# ---------------------------------------------------------------------------
def cache_dataframe(df: pd.DataFrame) -> None:
    st.session_state["compteurs_cache_df"] = df


def get_cached_dataframe() -> pd.DataFrame | None:
    return st.session_state.get("compteurs_cache_df")
