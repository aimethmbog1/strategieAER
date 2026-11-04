"""
Mouvements de personnel — surcouche de session par-dessus le registre RH figé
du classeur (feuille « Données - Équipes »), sur le même principe que les
autres registres éditables de l'application (parc auto, fonds revolving,
suivi de projets) : on ne modifie JAMAIS la feuille source, on applique un
changement de poste/antenne en mémoire, pour la durée de la session.

Toutes les pages qui dépendent du personnel (Organigramme — qui héberge les
actions de mouvement —, Équipes terrain, Home, besoins d'acquisition de
véhicules côté chauffeurs) doivent lire le registre EFFECTIF renvoyé par
`get_effective_roster()`, jamais `data.equipes_rows` / `data.unassigned`
directement, pour qu'un mouvement se répercute partout automatiquement.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from .auth import peut_modifier
from .storage import charger, enregistrer

MANQUANT = "— MANQUANT —"
MOUVEMENTS_COLUMNS = ["Horodatage", "Description"]


def _profil_from_role(role: str | None) -> str:
    """Déduit un « Profil » (référentiel du pool non affecté) à partir d'un
    « Rôle » d'équipe, pour qu'un agent qui quitte une équipe garde un profil
    cohérent dans le pool plutôt qu'un « Autre » générique."""
    r = (role or "").strip()
    if r == "Ingénieur":
        return "Ingénieur"
    if r.startswith("Technicien"):
        return "Technicien"
    if r == "Chauffeur":
        return "Chauffeur"
    return "Autre"


def _signature(equipes_rows: pd.DataFrame | None, unassigned: pd.DataFrame | None) -> str:
    """Signature bon marché du registre source, pour détecter un changement de
    classeur chargé (nouvel upload) et réinitialiser les mouvements de session
    en conséquence — on ne mélange jamais les mouvements d'un ancien classeur
    avec un nouveau."""
    n1 = 0 if equipes_rows is None else len(equipes_rows)
    n2 = 0 if unassigned is None else len(unassigned)
    first_name = ""
    if equipes_rows is not None and not equipes_rows.empty and "Nom" in equipes_rows.columns:
        first_name = str(equipes_rows["Nom"].iloc[0])
    return f"{n1}|{n2}|{first_name}"


def get_effective_roster(equipes_rows: pd.DataFrame | None, unassigned: pd.DataFrame | None
                          ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Renvoie (equipes_rows_effectif, unassigned_effectif) : une copie éditable
    tenue en session, initialisée depuis les données réelles du classeur au
    premier appel (ou si un nouveau classeur est chargé), puis mise à jour par
    `appliquer_mouvement`. Ne modifie jamais les DataFrames d'origine."""
    sig = _signature(equipes_rows, unassigned)
    if st.session_state.get("personnel_sig") != sig:
        st.session_state["personnel_sig"] = sig
        # Mouvements enregistrés durablement pour CE classeur source ? On les reprend.
        stockee = charger("personnel_signature")
        if stockee is not None and not stockee.empty and str(stockee.iloc[0, 0]) == sig:
            eq_s, pool_s, mv_s = charger("personnel_equipes"), charger("personnel_unassigned"), charger("personnel_mouvements")
            if eq_s is not None and pool_s is not None:
                st.session_state["personnel_equipes"] = eq_s
                st.session_state["personnel_unassigned"] = pool_s
                st.session_state["personnel_mouvements"] = (
                    mv_s if mv_s is not None else pd.DataFrame(columns=MOUVEMENTS_COLUMNS))
                return st.session_state["personnel_equipes"], st.session_state["personnel_unassigned"]
        st.session_state["personnel_equipes"] = (
            equipes_rows.copy() if equipes_rows is not None else pd.DataFrame()
        )
        st.session_state["personnel_unassigned"] = (
            unassigned.copy() if unassigned is not None else pd.DataFrame()
        )
        st.session_state["personnel_mouvements"] = pd.DataFrame(columns=MOUVEMENTS_COLUMNS)
    return st.session_state["personnel_equipes"], st.session_state["personnel_unassigned"]


def get_mouvements() -> pd.DataFrame:
    return st.session_state.get("personnel_mouvements", pd.DataFrame(columns=MOUVEMENTS_COLUMNS))


def reinitialiser_mouvements() -> None:
    """Revient au registre tel que lu dans le classeur, en effaçant tous les
    mouvements appliqués cette session."""
    st.session_state.pop("personnel_sig", None)
    st.session_state.pop("personnel_equipes", None)
    st.session_state.pop("personnel_unassigned", None)
    st.session_state.pop("personnel_mouvements", None)
    if peut_modifier():
        enregistrer("personnel_signature", pd.DataFrame({"signature": [""]}), "réinitialisation des mouvements")


def personnel_options(equipes_rows: pd.DataFrame, unassigned: pd.DataFrame) -> list[dict]:
    """Liste des agents déplaçables : agents réels en équipe (hors postes
    vacants « — MANQUANT — ») + agents du pool non affecté."""
    options: list[dict] = []
    if equipes_rows is not None and not equipes_rows.empty:
        occ = equipes_rows[equipes_rows["Nom"].astype(str).str.strip() != MANQUANT]
        for idx, row in occ.iterrows():
            zone = f" Z{row['Zone']}" if pd.notna(row.get("Zone")) else ""
            options.append({
                "key": f"equipe::{idx}",
                "label": f"{row['Nom']} — {row['Rôle']} ({row['Antenne']}{zone})",
                "source": "equipe", "index": idx,
            })
    if unassigned is not None and not unassigned.empty:
        for idx, row in unassigned.iterrows():
            options.append({
                "key": f"pool::{idx}",
                "label": f"{row['Nom']} — non affecté ({row.get('Poste (fichier RH)', '—') or '—'})",
                "source": "pool", "index": idx,
            })
    return options


def destination_options(equipes_rows: pd.DataFrame) -> list[dict]:
    """Postes cibles possibles : chaque ligne d'équipe (Antenne/Zone/Rôle),
    vacante ou déjà occupée (dans ce cas l'occupant actuel sera échangé avec
    l'agent déplacé), + le pool « non affecté »."""
    options: list[dict] = [{
        "key": "pool", "label": "📥 Personnel non affecté à une équipe (pool)",
        "target": "pool", "index": None,
    }]
    if equipes_rows is not None and not equipes_rows.empty:
        for idx, row in equipes_rows.iterrows():
            occupe = str(row["Nom"]).strip() != MANQUANT
            zone = f" Z{row['Zone']}" if pd.notna(row.get("Zone")) else ""
            label = f"{row['Rôle']} — {row['Antenne']}{zone}"
            label += f" (occupé par {row['Nom']})" if occupe else " (poste vacant)"
            options.append({"key": f"equipe::{idx}", "label": label, "target": "equipe", "index": idx})
    return options


def appliquer_mouvement(equipes_rows: pd.DataFrame, unassigned: pd.DataFrame,
                         source: dict, destination: dict) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """Applique un mouvement de personnel et renvoie (equipes_rows, unassigned,
    description) — ne lève jamais d'exception sur une combinaison incohérente,
    renvoie une description expliquant pourquoi rien n'a changé le cas échéant.

    Règles :
      - équipe → équipe occupée : ÉCHANGE des deux agents.
      - équipe → équipe vacante : l'agent prend le poste, son ancien poste devient vacant.
      - équipe → pool : l'agent quitte son équipe (poste vacant), rejoint le pool.
      - pool → équipe occupée : ÉCHANGE (l'occupant rejoint le pool).
      - pool → équipe vacante : l'agent du pool prend le poste, quitte le pool.
      - pool → pool : opération sans effet.
    """
    eq = equipes_rows.copy()
    pool = unassigned.copy()

    if source["source"] == "pool" and destination["target"] == "pool":
        return eq, pool, "Aucun changement (l'agent est déjà dans le pool non affecté)."

    if source["source"] == "equipe":
        src_row = eq.loc[source["index"]]
    else:
        src_row = pool.loc[source["index"]]
    src_nom = src_row["Nom"]
    src_poste = src_row.get("Poste (fichier RH)", "—")

    if destination["target"] == "equipe":
        dst_idx = destination["index"]
        if source["source"] == "equipe" and source["index"] == dst_idx:
            return eq, pool, "Aucun changement (poste de départ identique au poste d'arrivée)."

        dst_row = eq.loc[dst_idx]
        dst_occupe = str(dst_row["Nom"]).strip() != MANQUANT
        dst_label = f"{dst_row['Rôle']} — {dst_row['Antenne']}"
        displaced_nom = dst_row["Nom"] if dst_occupe else None
        displaced_poste = dst_row.get("Poste (fichier RH)", "—") if dst_occupe else None
        displaced_role = dst_row["Rôle"] if dst_occupe else None

        # L'agent déplacé prend la case destination.
        eq.loc[dst_idx, "Nom"] = src_nom
        eq.loc[dst_idx, "Poste (fichier RH)"] = src_poste
        eq.loc[dst_idx, "Statut"] = "OK"

        if source["source"] == "equipe":
            src_idx = source["index"]
            if dst_occupe:
                # Échange : l'occupant de la destination prend l'ancien poste de la source.
                eq.loc[src_idx, "Nom"] = displaced_nom
                eq.loc[src_idx, "Poste (fichier RH)"] = displaced_poste
                eq.loc[src_idx, "Statut"] = "OK"
            else:
                eq.loc[src_idx, "Nom"] = MANQUANT
                eq.loc[src_idx, "Poste (fichier RH)"] = None
                eq.loc[src_idx, "Statut"] = "MANQUE"
        else:
            # La source venait du pool : la retirer du pool.
            pool = pool.drop(index=source["index"]).reset_index(drop=True)
            if dst_occupe:
                # L'occupant déplacé rejoint le pool.
                pool = pd.concat([pool, pd.DataFrame([{
                    "Nom": displaced_nom, "Poste (fichier RH)": displaced_poste,
                    "Profil": _profil_from_role(displaced_role),
                }])], ignore_index=True)

        desc = f"{src_nom} → {dst_label}"
        if dst_occupe:
            desc += f" (échange avec {displaced_nom}, renvoyé " + (
                "au pool non affecté)" if source["source"] == "pool" else f"vers l'ancien poste de {src_nom})"
            )
        return eq, pool, desc

    # destination == pool (uniquement valide si la source vient d'une équipe,
    # déjà filtré en amont pour pool → pool)
    src_idx = source["index"]
    src_role = eq.loc[src_idx, "Rôle"]
    eq.loc[src_idx, "Nom"] = MANQUANT
    eq.loc[src_idx, "Poste (fichier RH)"] = None
    eq.loc[src_idx, "Statut"] = "MANQUE"
    pool = pd.concat([pool, pd.DataFrame([{
        "Nom": src_nom, "Poste (fichier RH)": src_poste, "Profil": _profil_from_role(src_role),
    }])], ignore_index=True)
    return eq, pool, f"{src_nom} → Personnel non affecté à une équipe"


def enregistrer_mouvement(description: str) -> None:
    log = get_mouvements()
    nouvelle = pd.DataFrame([{
        "Horodatage": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Description": description,
    }])
    if not peut_modifier():
        # consultation seule : on annule le mouvement appliqué en session
        for k in ("personnel_sig", "personnel_equipes", "personnel_unassigned", "personnel_mouvements"):
            st.session_state.pop(k, None)
        st.warning("🔒 Votre profil est en consultation seule : le mouvement n'a pas été appliqué.")
        return
    st.session_state["personnel_mouvements"] = pd.concat([log, nouvelle], ignore_index=True)
    enregistrer("personnel_equipes", st.session_state["personnel_equipes"], description)
    enregistrer("personnel_unassigned", st.session_state["personnel_unassigned"], description)
    enregistrer("personnel_mouvements", st.session_state["personnel_mouvements"], description)
    enregistrer("personnel_signature", pd.DataFrame({"signature": [st.session_state.get("personnel_sig", "")]}),
                "empreinte du classeur source")


def effectif_actuel_par_antenne(equipes_rows: pd.DataFrame | None) -> pd.Series:
    """Nombre d'agents réellement en poste (hors « — MANQUANT — »), toutes
    lignes d'équipe confondues (postes-types + personnel additionnel), par
    antenne — recalculé en direct à partir du registre EFFECTIF, donc reflète
    immédiatement tout mouvement de personnel."""
    if equipes_rows is None or equipes_rows.empty or "Antenne" not in equipes_rows.columns:
        return pd.Series(dtype="int64")
    occ = equipes_rows[equipes_rows["Nom"].astype(str).str.strip() != MANQUANT]
    return occ.groupby("Antenne").size()


STANDARD_ROLES = ["Ingénieur", "Technicien 1", "Technicien 2", "Chauffeur"]


def couverture_par_antenne(equipes_rows: pd.DataFrame | None) -> pd.DataFrame:
    """Taux de couverture des 4 postes-types (Ingénieur/Technicien 1/Technicien
    2/Chauffeur), par antenne RH — recalculé en direct à partir du registre
    EFFECTIF (classeur + mouvements de personnel de la session). Le personnel
    additionnel (rôle hors postes-types) n'entre pas dans ce calcul, par
    cohérence avec la page « Équipes terrain » et l'onglet RH de Home."""
    cols = ["Antenne", "Postes-types suivis", "Pourvus", "Manquants", "Taux de couverture (%)", "Effectif total (avec additionnel)"]
    if equipes_rows is None or equipes_rows.empty or "Antenne" not in equipes_rows.columns:
        return pd.DataFrame(columns=cols)
    std = equipes_rows[equipes_rows["Rôle"].isin(STANDARD_ROLES)]
    total_effectif = effectif_actuel_par_antenne(equipes_rows)
    rows = []
    for antenne, grp in std.groupby("Antenne"):
        total = len(grp)
        ok = int((grp["Statut"] == "OK").sum())
        rows.append({
            "Antenne": antenne,
            "Postes-types suivis": total,
            "Pourvus": ok,
            "Manquants": total - ok,
            "Taux de couverture (%)": round(ok / total * 100, 1) if total else 0.0,
            "Effectif total (avec additionnel)": int(total_effectif.get(antenne, 0)),
        })
    return pd.DataFrame(rows, columns=cols).sort_values("Antenne").reset_index(drop=True)
