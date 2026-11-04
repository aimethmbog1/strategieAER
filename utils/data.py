"""
Couche d'accès aux données pour le tableau de bord AER.

Toute la lecture du classeur Excel est centralisée ici : chaque fonction
publique renvoie une structure Python "propre" (DataFrame, dict, liste)
prête à afficher, jamais une cellule Excel brute. La localisation des
tableaux dans les feuilles se fait par RECHERCHE DE TITRE (texte des
bandeaux de section), pas par numéro de ligne codé en dur : si une feuille
est régénérée avec quelques lignes de plus ou de moins, l'application
continue de fonctionner.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Optional

import openpyxl
import pandas as pd
import streamlit as st

NAVY = "#1F3864"
BLUE = "#2E5C99"
GOLD = "#C9A24B"
RED = "#C00000"
GREEN = "#2E7D32"
AMBER = "#C77800"
GREY = "#8A8A8A"

STATUS_COLORS = {"Complète": GREEN, "Partielle": AMBER, "Critique": RED}
CATEGORICAL = [NAVY, BLUE, GOLD, GREEN, RED, AMBER, GREY, "#7A5C61"]


# ---------------------------------------------------------------------
# Chargement bas niveau
# ---------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def _load_workbook(file_bytes: bytes):
    return openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)


def _find_row(ws, text: str, col: Optional[int] = 1, start: int = 1, end: Optional[int] = None) -> Optional[int]:
    """Première ligne contenant `text` (insensible à la casse).
    Si `col` est fourni, ne regarde que cette colonne ; sinon balaie toutes
    les colonnes de la ligne (utile pour les bandeaux de section dont le
    texte est écrit sur la cellule ancre d'une plage fusionnée qui ne
    commence pas forcément en colonne A, ex. « STATUT DES 16 ÉQUIPES »
    écrit en colonne H)."""
    end = end or ws.max_row
    needle = text.upper()
    cols = [col] if col is not None else range(1, ws.max_column + 1)
    for r in range(start, end + 1):
        for c in cols:
            v = ws.cell(row=r, column=c).value
            if v and needle in str(v).upper():
                return r
    return None


def _find_header_row(ws, exact_text: str, col: int = 1, start: int = 1, end: Optional[int] = None) -> Optional[int]:
    """Trouve la ligne d'en-tête d'un tableau par ÉGALITÉ EXACTE (insensible
    à la casse/espaces) du texte de la cellule, contrairement à `_find_row`
    qui fait une recherche par sous-chaîne. Nécessaire car un bandeau de
    titre de section (« RÉPARTITION DES 499 SITES PAR ANTENNE PROPOSÉE »)
    peut contenir le nom de la colonne d'en-tête (« Antenne proposée ») en
    tant que sous-chaîne et serait sinon confondu avec l'en-tête réel."""
    end = end or ws.max_row
    needle = exact_text.strip().upper()
    for r in range(start, end + 1):
        v = ws.cell(row=r, column=col).value
        if v and str(v).strip().upper() == needle:
            return r
    return None


def _read_table(ws, header_row: int, col_start: int, col_end: int, max_rows: int = 500) -> pd.DataFrame:
    """Lit un tableau à partir de sa ligne d'en-tête, s'arrête à la première ligne
    totalement vide sur la plage de colonnes (ou à `max_rows`)."""
    headers = [ws.cell(row=header_row, column=c).value for c in range(col_start, col_end + 1)]
    headers = [h if h is not None else f"col{c}" for c, h in zip(range(col_start, col_end + 1), headers)]
    rows = []
    r = header_row + 1
    blanks = 0
    while r <= ws.max_row and (r - header_row) <= max_rows:
        vals = [ws.cell(row=r, column=c).value for c in range(col_start, col_end + 1)]
        if all(v is None or (isinstance(v, str) and v.strip() == "") for v in vals):
            blanks += 1
            if blanks >= 2:
                break
            r += 1
            continue
        blanks = 0
        rows.append(vals)
        r += 1
    df = pd.DataFrame(rows, columns=headers)
    # laisse tomber les colonnes 100% vides générées par des cellules fusionnées
    return df


@dataclass
class TeamRow:
    antenne: str
    zone: str
    role: str
    name: str
    poste: str
    statut: str


@dataclass
class AERData:
    kpis_solar: dict = field(default_factory=dict)
    kpis_rh: dict = field(default_factory=dict)
    grid: pd.DataFrame = None
    action_plan: pd.DataFrame = None
    profil_table: pd.DataFrame = None
    solar_table: pd.DataFrame = None
    rh_table: pd.DataFrame = None
    antennes_detail: pd.DataFrame = None
    sites: pd.DataFrame = None
    repartition: pd.DataFrame = None
    synthese_region: pd.DataFrame = None
    equipes_rows: pd.DataFrame = None
    unassigned: pd.DataFrame = None
    antenna_centroids: pd.DataFrame = None
    visites_mensuelles: pd.DataFrame = None
    notes_text: list[str] = field(default_factory=list)
    generated_on: str = ""


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


# ---------------------------------------------------------------------
# Parsing de la feuille "Dashboard"
# ---------------------------------------------------------------------
def _parse_dashboard(ws) -> tuple[dict, dict, pd.DataFrame, pd.DataFrame, pd.DataFrame, str]:
    gen_row = _find_row(ws, "Généré le", col=1, end=6)
    generated_on = str(ws.cell(row=gen_row, column=1).value) if gen_row else ""

    # --- KPI cards : lues par paire (ligne label / ligne valeur), peu importe
    #     leur position exacte de colonne (on scanne toute la largeur).
    def read_kpi_band(label_row: int) -> dict:
        out = {}
        value_row = label_row + 1
        c = 1
        while c <= ws.max_column:
            label = ws.cell(row=label_row, column=c).value
            if label and str(label).strip():
                val = ws.cell(row=value_row, column=c).value
                out[str(label).strip()] = val
            c += 1
        return out

    solar_kpi_row = _find_row(ws, "SITES INSTALLÉS", end=8)
    rh_kpi_row = _find_row(ws, "ÉQUIPES CONSTITUÉES", end=15)
    kpis_solar = read_kpi_band(solar_kpi_row) if solar_kpi_row else {}
    kpis_rh = read_kpi_band(rh_kpi_row) if rh_kpi_row else {}

    # --- Grille "STATUT DES 16 ÉQUIPES" (titre écrit en colonne H)
    grid_title_row = _find_row(ws, "STATUT DES 16", col=None)
    grid = pd.DataFrame()
    if grid_title_row:
        hdr = grid_title_row + 2
        grid = _read_table(ws, hdr, 8, 13, max_rows=20)

    # --- Table "MANQUES PAR PROFIL"
    profil_title_row = _find_row(ws, "MANQUES PAR PROFIL", col=None)
    profil_table = pd.DataFrame()
    if profil_title_row:
        hdr = profil_title_row + 2
        profil_table = _read_table(ws, hdr, 1, 5, max_rows=6)

    def _truncate_after_total(df: pd.DataFrame) -> pd.DataFrame:
        """`_read_table` only stops at 2 consecutive blank rows ; certaines
        feuilles n'ont qu'UNE ligne vide entre une ligne TOTAL et le titre de
        section suivant, qui se retrouve alors happé comme une ligne de
        données. On coupe systématiquement juste après la ligne TOTAL."""
        if df.empty:
            return df
        first_col = df.columns[0]
        total_idx = df.index[df[first_col].astype(str).str.upper().str.startswith("TOTAL")]
        return df.loc[: total_idx[0]] if len(total_idx) else df

    # --- Table parc solaire
    solar_title_row = _find_row(ws, "CHARGE ET DIMENSIONNEMENT", col=None)
    solar_table = pd.DataFrame()
    if solar_title_row:
        hdr = solar_title_row + 2
        solar_table = _truncate_after_total(_read_table(ws, hdr, 1, 8, max_rows=12))

    # --- Table RH manques par antenne
    rh_title_row = _find_row(ws, "MANQUES PAR ANTENNE", col=None)
    rh_table = pd.DataFrame()
    if rh_title_row:
        hdr = rh_title_row + 2
        rh_table = _truncate_after_total(_read_table(ws, hdr, 1, 7, max_rows=12))

    # --- Plan d'action prioritaire
    action_title_row = _find_row(ws, "PLAN D'ACTION", col=None)
    action_plan = pd.DataFrame()
    if action_title_row:
        hdr = action_title_row + 2
        action_plan = _read_table(ws, hdr, 1, 5, max_rows=20)

    return kpis_solar, kpis_rh, grid, profil_table, solar_table, rh_table, action_plan, generated_on


# ---------------------------------------------------------------------
# Parsing de la feuille "Données - Équipes"
# ---------------------------------------------------------------------
def _parse_equipes(ws) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    current_antenne = None
    current_zone = None
    title_row = _find_row(ws, "PERSONNEL NON AFFECT")
    last_main_row = (title_row - 1) if title_row else ws.max_row
    for r in range(5, last_main_row + 1):
        a = ws.cell(row=r, column=1).value
        z = ws.cell(row=r, column=2).value
        role = ws.cell(row=r, column=3).value
        name = ws.cell(row=r, column=4).value
        poste = ws.cell(row=r, column=5).value
        statut = ws.cell(row=r, column=6).value
        if a and str(a).strip():
            current_antenne = str(a).strip()
        if z is not None and str(z).strip() != "":
            current_zone = z
        if role is None and name is None:
            continue
        rows.append({
            "Antenne": current_antenne,
            "Zone": current_zone,
            "Rôle": role,
            "Nom": name,
            "Poste (fichier RH)": poste,
            "Statut": statut,
        })
    equipes_df = pd.DataFrame(rows)
    if not equipes_df.empty:
        equipes_df["Poste (fichier RH)"] = equipes_df["Poste (fichier RH)"].fillna("—")

    unassigned = pd.DataFrame()
    if title_row:
        hdr = title_row + 1
        unassigned = _read_table(ws, hdr, 1, 3, max_rows=60)
    return equipes_df, unassigned


@st.cache_data(show_spinner="Lecture du classeur…")
def load_workbook_data(file_bytes: bytes) -> AERData:
    wb = _load_workbook(file_bytes)
    data = AERData()

    if "Dashboard" in wb.sheetnames:
        ws = wb["Dashboard"]
        (data.kpis_solar, data.kpis_rh, data.grid, data.profil_table,
         data.solar_table, data.rh_table, data.action_plan, data.generated_on) = _parse_dashboard(ws)

    if "Antennes — Détail solaire" in wb.sheetnames:
        ws = wb["Antennes — Détail solaire"]
        hdr = _find_header_row(ws, "Antenne", end=8) or 4
        det = _read_table(ws, hdr, 1, 13, max_rows=15)
        # la feuille contient d'autres mini-tableaux (TOTAL, vue par groupe,
        # constat) juste en dessous, séparés par une seule ligne vide : on
        # s'arrête à la première ligne "TOTAL" pour ne garder que les 9
        # antennes individuelles.
        total_idx = det.index[det["Antenne"].astype(str).str.upper() == "TOTAL"]
        if len(total_idx):
            det = det.loc[: total_idx[0] - 1]
        numeric_cols = ["Nb sites", "Puissance totale (kWc)", "Chef + admin", "Ingénieurs techniques",
                         "Agents communautaires", "Effectif total", "Sites par agent",
                         "% du total sites", "% de la puissance totale"]
        for col in numeric_cols:
            if col in det.columns:
                det[col] = pd.to_numeric(det[col], errors="coerce")
        if "Rattachée à" in det.columns:
            det["Rattachée à"] = det["Rattachée à"].fillna("—")
        data.antennes_detail = det

    if "Données sites" in wb.sheetnames:
        ws = wb["Données sites"]
        data.sites = _read_table(ws, 1, 1, 10, max_rows=600)

    if "Répartition par antenne" in wb.sheetnames:
        ws = wb["Répartition par antenne"]
        hdr = _find_header_row(ws, "Antenne proposée", end=8) or 4
        data.repartition = _read_table(ws, hdr, 1, 6, max_rows=600)

    if "Synthèse par région" in wb.sheetnames:
        ws = wb["Synthèse par région"]
        hdr = _find_header_row(ws, "Région", end=8) or 4
        syn = _read_table(ws, hdr, 1, 6, max_rows=300)
        # tableau en mode plan à 2 niveaux : une ligne "sous-total région"
        # (Département/Arrondissement vides) suivie de ses lignes détail par
        # arrondissement. On propage la région vers le bas pour permettre le
        # filtrage, et on marque le niveau de chaque ligne pour ne jamais
        # sommer un sous-total région avec ses propres lignes détail
        # (double comptage).
        if not syn.empty:
            syn["Région"] = syn["Région"].ffill()
            syn["Niveau"] = syn["Département"].apply(lambda v: "Détail (arrondissement)" if pd.notna(v) else "Sous-total région")
        data.synthese_region = syn

        # petit tableau annexe (colonnes I-K) : fréquence de visite mensuelle
        # proposée par antenne, référentiel RH (noms de région, pas les
        # antennes solaires) — donnée réelle de la feuille, simplement
        # surfacée telle quelle, jamais recalculée.
        vm_hdr = _find_header_row(ws, "antennes", col=9, end=8)
        if vm_hdr:
            vm = _read_table(ws, vm_hdr, 9, 11, max_rows=15)
            vm.columns = ["Antenne (référentiel RH)", "Visites/mois (calcul)", "Visites/mois (arrondi)"]
            vm = vm.dropna(subset=["Antenne (référentiel RH)"])
            data.visites_mensuelles = vm

    if "Données - Équipes" in wb.sheetnames:
        ws = wb["Données - Équipes"]
        data.equipes_rows, data.unassigned = _parse_equipes(ws)

    if data.sites is not None and not data.sites.empty:
        from .geo import compute_antenna_centroids, attach_site_distances
        data.antenna_centroids = compute_antenna_centroids(data.sites, data.antennes_detail)
        data.sites = attach_site_distances(data.sites, data.antenna_centroids)

    if "Notes & méthodologie" in wb.sheetnames:
        ws = wb["Notes & méthodologie"]
        texts = []
        for r in range(1, ws.max_row + 1):
            v = ws.cell(row=r, column=1).value
            if v and str(v).strip():
                texts.append(str(v).strip())
        data.notes_text = texts

    return data


@st.cache_data(show_spinner=False)
def antennes_hierarchy(antennes_detail: pd.DataFrame) -> list[dict]:
    """Reconstruit la hiérarchie Siège -> antennes principales -> annexes
    à partir de la colonne 'Rattachée à' de la feuille Antennes — Détail solaire."""
    if antennes_detail is None or antennes_detail.empty:
        return []
    out = []
    for _, row in antennes_detail.iterrows():
        out.append({
            "antenne": row.get("Antenne"),
            "type": row.get("Type"),
            "rattachee_a": row.get("Rattachée à"),
            "effectif": row.get("Effectif total"),
            "sites": row.get("Nb sites"),
        })
    return out
