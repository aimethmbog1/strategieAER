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
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import io

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
# Phase par préfixe du numéro de compteur — convention communiquée par
# l'utilisateur (pas une règle officielle documentée dans les exports
# Holley) : le numéro de série du compteur (`sn`, colonne « SN » des exports
# Holley — PAS « Old Consumer No. », qui est un numéro d'abonné commençant
# toujours par 9000… et ne correspond donc jamais à aucun préfixe) commençant
# par « 251 » appartient à la Phase 1, par « 241 » à la Phase 2, par « 5 » à
# la Phase 3. Si la colonne `sn` est absente (fichier non Holley mappé à la
# main), on se rabat sur `numero_compteur`. L'association se fait par ORDRE (1er
# préfixe -> 1re ligne du tableau des phases, etc.), jamais par nom, pour
# rester valable même si l'utilisateur renomme ses phases dans la barre
# latérale. À ajuster ici si une autre convention s'applique.
# ---------------------------------------------------------------------------
PREFIXES_COMPTEUR_PHASE = [("251", 0), ("241", 1), ("5", 2)]


def assign_phase_by_prefix(
    df: pd.DataFrame, phases: pd.DataFrame,
    prefixes: list[tuple[str, int]] = PREFIXES_COMPTEUR_PHASE,
) -> pd.Series:
    """Classe chaque ligne de `df` par préfixe de `sn` (à défaut `numero_compteur`). Renvoie
    None (valeur manquante) pour un numéro ne correspondant à aucun préfixe
    connu, ou si la phase à l'index demandé n'est pas définie dans `phases`
    — jamais une phase devinée. Les préfixes les plus longs sont testés en
    premier, pour qu'un préfixe plus spécifique l'emporte en cas de
    chevauchement (ex. un futur préfixe à 1 chiffre ne doit pas avaler un
    préfixe à 3 chiffres qui commence par le même chiffre)."""
    resultat = pd.Series([None] * len(df), index=df.index, dtype="object")
    colonne = "sn" if "sn" in df.columns else "numero_compteur"
    if colonne not in df.columns or df.empty:
        return resultat
    noms_phases = phases["Phase"].tolist()
    numeros = (df[colonne].astype(str).str.replace("\x00", "", regex=False)
               .str.strip().str.replace(r"\.0$", "", regex=True))
    non_classes = pd.Series(True, index=df.index)
    for prefixe, idx in sorted(prefixes, key=lambda p: -len(p[0])):
        if idx >= len(noms_phases) or pd.isna(noms_phases[idx]) or not str(noms_phases[idx]).strip():
            continue
        masque = non_classes & numeros.str.startswith(prefixe)
        resultat[masque] = str(noms_phases[idx]).strip()
        non_classes &= ~masque
    return resultat


def assign_phases_combined(
    df: pd.DataFrame, phases: pd.DataFrame,
    prefixes: list[tuple[str, int]] = PREFIXES_COMPTEUR_PHASE,
) -> tuple[pd.Series, pd.Series]:
    """Classement final par phase, en deux temps : le préfixe du numéro de
    compteur décide quand il correspond à une convention connue (plus
    fiable, basé sur un identifiant stable plutôt qu'une date parfois mal
    renseignée) ; sinon on retombe sur le classement par plage de dates
    (`assign_phases`). Renvoie `(phase_finale, desaccord)` où `desaccord`
    est un masque booléen : True quand les deux méthodes désignent une
    phase différente pour la même ligne — à vérifier manuellement, jamais
    résolu silencieusement en faveur de l'une ou l'autre."""
    phase_date = assign_phases(df, phases)
    phase_prefixe = assign_phase_by_prefix(df, phases, prefixes)
    phase_finale = phase_prefixe.where(phase_prefixe.notna(), phase_date)
    desaccord = phase_prefixe.notna() & phase_date.notna() & (phase_prefixe != phase_date)
    return phase_finale, desaccord


# ---------------------------------------------------------------------------
# Format Holley (format réel des fichiers fournis par l'AER)
# ---------------------------------------------------------------------------
COLONNES_HOLLEY_ATTENDUES = {"Full Address", "Template Code"}


def est_format_holley(raw: pd.DataFrame) -> bool:
    return COLONNES_HOLLEY_ATTENDUES.issubset(set(raw.columns))


@st.cache_data(show_spinner=False, max_entries=64)
def lire_fichier_compteurs(nom: str, contenu: bytes) -> pd.DataFrame:
    """Lit la première feuille d'un export (mis en cache par contenu : un fichier déjà
    lu n'est pas relu à chaque interaction)."""
    feuilles = read_excel_sheet_names(io.BytesIO(contenu))
    return load_excel(io.BytesIO(contenu), sheet_name=feuilles[0] if feuilles else 0)


def read_excel_sheet_names(uploaded_file) -> list[str]:
    try:
        return pd.ExcelFile(uploaded_file).sheet_names
    except Exception:  # noqa: BLE001
        return []


def _sans_nul(v):
    """Retire les caractères nuls (\\x00) : certains exports Holley .xls
    stockent le texte avec un \\x00 après chaque caractère (« 2\\x004\\x001… »),
    ce qui casse la détection du format, les préfixes 241/251 et les noms de
    localités. Constaté sur 01-07-2026.xls."""
    return v.replace("\x00", "").strip() if isinstance(v, str) else v


def load_excel(uploaded_file, sheet_name=0) -> pd.DataFrame:
    # dtype=str sur SN : un numéro de série lu comme nombre perdrait ses zéros
    # de tête éventuels ou passerait en notation scientifique.
    raw = pd.read_excel(uploaded_file, sheet_name=sheet_name, dtype={"SN": str})
    raw.columns = [_sans_nul(str(c)) for c in raw.columns]
    for c in raw.columns:
        if raw[c].dtype == object or str(raw[c].dtype) in ("str", "string"):
            raw[c] = raw[c].map(_sans_nul)
    return raw


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
        # Numéro de série physique du compteur — c'est LUI qui porte la phase
        # (préfixe 251/241/5), pas le numéro d'abonné ci-dessus.
        if "SN" in raw.columns:
            bloc["sn"] = (raw["SN"].astype(str).str.replace("\x00", "", regex=False)
                          .str.strip().str.replace(r"\.0$", "", regex=True))
        bloc["periode"] = pd.Timestamp(f["periode"]).to_period("M").to_timestamp()
        bloc["nom_fichier"] = f["nom"]
        blocs.append(bloc)
    out = pd.concat(blocs, ignore_index=True)
    out.loc[out["localite_brute"].isin(["0", "", "NAN", "NONE"]), "localite_brute"] = "(localité non renseignée)"
    out["localite"] = out["localite_brute"]  # remplacé par la version nettoyée une fois validée par l'utilisateur
    return out


_CHEMIN_SITES_OFFICIELS = Path(__file__).resolve().parent.parent / "data" / "sites_officiels_aer.csv"
_CHEMIN_PUISSANCES_SITES = Path(__file__).resolve().parent.parent / "data" / "puissances_sites_aer.csv"

# Convention de dimensionnement assumée (communiquée par l'utilisateur, pas une
# règle AER documentée trouvée dans les fichiers de cette application) : un
# site ne peut théoriquement admettre, comme nombre de compteurs, que sa
# puissance installée divisée par 400 W par compteur. Diviseur entier
# (`//`) : un site ne peut pas admettre une fraction de compteur.
WATTS_PAR_COMPTEUR = 400
SEUIL_SATURATION_AVERTISSEMENT = 0.80
SEUIL_SATURATION_CRITIQUE = 1.00


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


def load_puissances_sites() -> pd.DataFrame:
    """Puissance installée (kWc) des 499 sites officiels du parc solaire AER
    — même principe et même source que `load_official_sites()` : extraite
    une fois pour toutes du classeur `Gestion_Parc_Solaire_AER2027_DASHBOARD.
    xlsx` (feuille « Données sites », colonne « Puissance (kWc) ») et
    embarquée ici comme référence statique. Cette application continue de
    ne JAMAIS lire ce classeur à l'exécution — seul un instantané de deux de
    ses colonnes (région/antenne, puissance) est embarqué dans `data/`.
    Un site dont le nom apparaît deux fois dans le classeur source
    (« Mbamti-Katarko », deux sites distincts partageant le même nom) ne
    garde que sa première occurrence, exactement comme `sites_officiels_aer.
    csv` — pas une correction propre à cette fonction."""
    if not _CHEMIN_PUISSANCES_SITES.exists():
        return pd.DataFrame(columns=["nom", "puissance_kwc", "max_compteurs"])
    df = pd.read_csv(_CHEMIN_PUISSANCES_SITES)
    df["max_compteurs"] = (df["puissance_kwc"] * 1000 // WATTS_PAR_COMPTEUR).astype(int)
    return df


def statut_saturation(taux: float | None) -> str:
    """'neutral' si le taux est inconnu (site sans puissance de référence),
    'critical' si le site dépasse sa capacité théorique (>= 100 %), 'warning'
    au-delà de 80 %, 'ok' en dessous. Seuils calqués sur ceux déjà utilisés
    pour les objectifs par phase (`target_status`) — mêmes paliers 80 %/100 %,
    lecture inversée (ici, plus haut = plus près de la saturation)."""
    if taux is None or pd.isna(taux):
        return "neutral"
    if taux >= SEUIL_SATURATION_CRITIQUE:
        return "critical"
    if taux >= SEUIL_SATURATION_AVERTISSEMENT:
        return "warning"
    return "ok"


def saturation_par_site(df: pd.DataFrame, sites_ref: pd.DataFrame, puissances: pd.DataFrame) -> pd.DataFrame:
    """Taux de saturation de chaque site officiel : compteurs installés
    rapportés à sa capacité théorique (puissance ÷ 400 W/compteur). Un site
    du référentiel sans aucun compteur installé reste dans le résultat avec
    un taux de 0 % (jamais omis — c'est aussi une information utile). Une
    localité installée qui ne correspond à aucun site officiel (sous-
    localité, quartier) n'apparaît pas ici : elle n'a pas de puissance de
    référence, donc pas de capacité théorique calculable — déjà signalée par
    ailleurs (onglet « Par région », compteur « hors référentiel »)."""
    if puissances.empty or sites_ref.empty or "localite" not in df.columns:
        return pd.DataFrame()
    installes = df["localite"].astype(str).str.strip().value_counts().rename("compteurs_installes")
    base = puissances.merge(
        sites_ref[["nom", "region", "antenne"]].drop_duplicates(subset="nom"), on="nom", how="left",
    )
    base = base.join(installes, on="nom")
    base["compteurs_installes"] = base["compteurs_installes"].fillna(0).astype(int)
    base["taux_saturation"] = base.apply(
        lambda r: (r["compteurs_installes"] / r["max_compteurs"]) if r["max_compteurs"] > 0 else None, axis=1,
    )
    base["statut"] = base["taux_saturation"].apply(statut_saturation)
    return base.sort_values("taux_saturation", ascending=False, na_position="last").reset_index(drop=True)


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
# Objectifs par phase (aucune cible chiffrée n'existe dans les exports Holley
# ni ailleurs dans cette application — purement déclaratif, saisi par
# l'utilisateur dans la barre latérale, comme les phases elles-mêmes)
# ---------------------------------------------------------------------------
def default_targets(noms_phases: list[str]) -> pd.DataFrame:
    """Point de départ pour le tableau d'objectifs (barre latérale) : une
    ligne par phase définie, objectif à 0 (« pas de suivi ») par défaut."""
    return pd.DataFrame({"Phase": noms_phases, "Objectif (compteurs)": [0] * len(noms_phases)})


def target_status(realise: int, objectif: int) -> str:
    """'neutral' si aucun objectif saisi (0), 'ok' si >= objectif, 'warning'
    si >= 80 % de l'objectif, 'critical' sinon. Seuil des 80 % assumé par
    défaut, faute de tolérance officielle communiquée — à ajuster si l'AER
    en a une différente."""
    if objectif <= 0:
        return "neutral"
    ratio = realise / objectif
    if ratio >= 1:
        return "ok"
    if ratio >= 0.8:
        return "warning"
    return "critical"


# ---------------------------------------------------------------------------
# Couverture des localités officielles — combien des 499 sites du parc
# solaire ont au moins un compteur installé
# ---------------------------------------------------------------------------
def coverage_stats(df: pd.DataFrame, sites_ref: pd.DataFrame) -> dict:
    """Correspondance EXACTE entre `df['localite']` (déjà nettoyée et
    rapprochée des sites officiels par `locality_cleanup_ui`) et
    `sites_ref['nom']` — pas une nouvelle passe de similarité de texte : ce
    rapprochement a déjà eu lieu, avec validation de l'utilisateur, au
    chargement des données."""
    if sites_ref.empty:
        return {"couvertes": 0, "total": 0, "taux": None, "non_couvertes": []}
    noms_officiels = set(sites_ref["nom"].astype(str).str.strip())
    noms_installes = set(df["localite"].astype(str).str.strip()) if "localite" in df else set()
    couvertes = noms_officiels & noms_installes
    non_couvertes = sorted(noms_officiels - noms_installes)
    total = len(noms_officiels)
    return {
        "couvertes": len(couvertes), "total": total,
        "taux": (len(couvertes) / total) if total else None,
        "non_couvertes": non_couvertes,
    }


# ---------------------------------------------------------------------------
# Répartition régionale — PAS une carte géographique (`sites_officiels_aer.csv`
# ne contient aucune coordonnée GPS, contrairement au classeur Excel du
# tableau de bord principal que cette application ne lit pas) : seulement un
# regroupement par région/antenne à partir des colonnes déjà présentes dans
# le référentiel des sites officiels.
# ---------------------------------------------------------------------------
def regional_breakdown(df: pd.DataFrame, sites_ref: pd.DataFrame) -> pd.DataFrame:
    """Rattache chaque compteur à la région/antenne de sa localité par
    correspondance EXACTE avec `sites_ref`. Une localité qui ne correspond à
    aucun site officiel (sous-localité, quartier) reste « (hors
    référentiel) » — jamais une région devinée."""
    out = df.copy()
    if sites_ref.empty or "localite" not in out.columns:
        out["region"] = "(référentiel indisponible)"
        out["antenne"] = "(référentiel indisponible)"
        return out
    lookup = sites_ref.drop_duplicates(subset="nom").set_index("nom")[["region", "antenne"]]
    out = out.join(lookup, on="localite")
    out["region"] = out["region"].fillna("(hors référentiel)")
    out["antenne"] = out["antenne"].fillna("(hors référentiel)")
    return out


# ---------------------------------------------------------------------------
# Qualité des données — repère, ne corrige jamais automatiquement
# ---------------------------------------------------------------------------
def detect_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """Compteurs dont le numéro (`numero_compteur`) apparaît plus d'une fois
    dans l'ensemble des lots chargés — signale un double comptage possible
    (lot déposé deux fois, chevauchement entre deux exports). Jamais
    dédoublonné automatiquement : à vérifier manuellement."""
    if "numero_compteur" not in df.columns or df.empty:
        return pd.DataFrame()
    comptes = df["numero_compteur"].value_counts()
    doublons = comptes[comptes > 1]
    if doublons.empty:
        return pd.DataFrame()
    lignes = df[df["numero_compteur"].isin(doublons.index)].copy()
    colonnes = [c for c in ["numero_compteur", "localite", "poste", "periode", "nom_fichier"] if c in lignes.columns]
    return lignes[colonnes].sort_values("numero_compteur")


def detect_dormant_postes(df: pd.DataFrame, seuil_jours: int = 90) -> pd.DataFrame:
    """Postes dont la dernière installation connue date de plus de
    `seuil_jours` par rapport à la période la plus récente de l'ensemble des
    données chargées — signale un poste potentiellement à l'arrêt
    (équipement, connectivité) pendant que d'autres restent actifs. Seuil
    assumé par défaut, faute de valeur officielle communiquée."""
    if "poste" not in df.columns or df.empty:
        return pd.DataFrame()
    reference = df["periode"].max()
    par_poste = df.groupby("poste").agg(
        Dernière_période=("periode", "max"), Compteurs=("poste", "size"),
    ).reset_index()
    par_poste["Jours depuis dernière installation"] = (reference - par_poste["Dernière_période"]).dt.days
    dormants = par_poste[par_poste["Jours depuis dernière installation"] > seuil_jours]
    return dormants.sort_values("Jours depuis dernière installation", ascending=False)


def data_quality_summary(df: pd.DataFrame) -> dict:
    """Part de lignes dont la localité ou le poste n'a pas pu être lu dans le
    fichier source (valeur sentinelle `(localité non renseignée)` /
    `(non renseigné)` posée par `build_from_holley_files`)."""
    total = len(df)
    if total == 0:
        return {}
    non_renseigne_loc = int((df.get("localite_brute") == "(localité non renseignée)").sum()) if "localite_brute" in df else 0
    non_renseigne_poste = int((df.get("poste") == "(non renseigné)").sum()) if "poste" in df else 0
    return {
        "total": total,
        "localites_non_renseignees": non_renseigne_loc,
        "taux_localites_non_renseignees": non_renseigne_loc / total,
        "postes_non_renseignes": non_renseigne_poste,
        "taux_postes_non_renseignes": non_renseigne_poste / total,
    }


# ---------------------------------------------------------------------------
# Export PDF — synthèse pour reporting institutionnel. fpdf2 : pure Python,
# sans dépendance système (contrairement à weasyprint), donc compatible
# Streamlit Community Cloud. `sections` : liste de dicts
# {"titre": str, "texte": str | None, "image_bytes": bytes | None,
#  "tableau": pd.DataFrame | None}.
# ---------------------------------------------------------------------------
_PDF_REMPLACEMENTS = {
    "—": "-", "–": "-", "’": "'", "‘": "'", "“": '"', "”": '"', "…": "...", " ": " ",
}


def _pdf_safe(texte) -> str:
    """La police de base (Helvetica) de fpdf2 ne couvre que le latin-1 — un
    tiret cadratin ou une puce issue des libellés de l'interface (qui
    contiennent aussi des emojis) fait planter l'export. Remplace la
    ponctuation courante hors-latin-1, puis neutralise tout caractère restant
    non supporté (emoji compris) plutôt que de faire échouer le téléchargement."""
    s = str(texte)
    for a, b in _PDF_REMPLACEMENTS.items():
        s = s.replace(a, b)
    return s.encode("latin-1", errors="replace").decode("latin-1")


def build_pdf_report(titre: str, sous_titre: str, genere_le: str,
                      kpis: list[tuple[str, str]], sections: list[dict]) -> bytes:
    from fpdf import FPDF

    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(31, 56, 100)
    pdf.cell(0, 10, _pdf_safe(titre), ln=True)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 7, _pdf_safe(sous_titre), ln=True)
    pdf.cell(0, 6, _pdf_safe(f"Genere le {genere_le}"), ln=True)
    pdf.ln(4)

    if kpis:
        col_w = (pdf.w - 2 * pdf.l_margin) / len(kpis)
        y0 = pdf.get_y()
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(31, 56, 100)
        x = pdf.l_margin
        for _, value in kpis:
            pdf.set_xy(x, y0)
            pdf.multi_cell(col_w, 6, _pdf_safe(value), align="C")
            x += col_w
        y_labels = y0 + 8
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(110, 110, 110)
        x = pdf.l_margin
        y_apres_labels = y_labels
        for label, _ in kpis:
            # `y_labels` fixe, pas `pdf.get_y()` repris d'une itération à l'autre :
            # sinon un libellé qui passe sur 2 lignes décale verticalement tous les
            # suivants (bug repéré en comparant le PDF rendu à la maquette).
            pdf.set_xy(x, y_labels)
            pdf.multi_cell(col_w, 4, _pdf_safe(label), align="C")
            y_apres_labels = max(y_apres_labels, pdf.get_y())
            x += col_w
        pdf.set_y(y_apres_labels)
        pdf.ln(6)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(4)

    for section in sections:
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(31, 56, 100)
        pdf.cell(0, 8, _pdf_safe(section["titre"]), ln=True)
        if section.get("texte"):
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(60, 60, 60)
            pdf.multi_cell(0, 5, _pdf_safe(section["texte"]))
        if section.get("image_bytes"):
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    tmp.write(section["image_bytes"])
                    tmp_path = tmp.name
                pdf.image(tmp_path, w=pdf.w - 2 * pdf.l_margin)
            finally:
                if tmp_path:
                    os.unlink(tmp_path)
        if section.get("tableau") is not None and not section["tableau"].empty:
            df_t = section["tableau"]
            col_w_t = (pdf.w - 2 * pdf.l_margin) / len(df_t.columns)
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_fill_color(230, 236, 245)
            pdf.set_text_color(31, 56, 100)
            for col in df_t.columns:
                pdf.cell(col_w_t, 6, _pdf_safe(str(col)[:28]), border=1, fill=True)
            pdf.ln()
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(40, 40, 40)
            for _, row in df_t.iterrows():
                for val in row:
                    pdf.cell(col_w_t, 5.5, _pdf_safe(str(val)[:28]), border=1)
                pdf.ln()
        pdf.ln(5)

    pdf.set_y(-15)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(140, 140, 140)
    pdf.cell(0, 8, "AER - Statistiques des compteurs (export Holley) - document genere automatiquement", align="C")

    return bytes(pdf.output())


# ------------------------------------------------------------------ cache de session
# Utilisé par la page d'accueil (onglet « Statistiques compteurs ») pour résumer les
# fichiers déposés dans la page « Statistiques des compteurs ».
def cache_dataframe(df: pd.DataFrame) -> None:
    st.session_state["compteurs_cache_df"] = df


def get_cached_dataframe() -> pd.DataFrame | None:
    return st.session_state.get("compteurs_cache_df")
