"""
Agent conseil — moteur de règles déterministe.

Choix d'architecture (validé avec l'utilisateur) : PAS d'appel à une API LLM.
Chaque recommandation est produite par une règle explicite, écrite et lisible
ci-dessous, et systématiquement reliée au chiffre réel qui la justifie
(jamais une affirmation sans le nombre qui la soutient). Aucune clé API,
aucun secret, aucun coût récurrent, aucun risque d'hallucination — cohérent
avec la philosophie « jamais de donnée inventée » appliquée partout ailleurs
dans l'application.

Ce moteur ne fait QUE relire des données déjà calculées ailleurs dans
l'application (plan d'action RH du classeur, registre de suivi de projets,
registre du Fonds revolving) et les reformule sous forme de conseils
priorisés. Il ne lit, n'écrit et n'invente aucune nouvelle donnée.
"""
from __future__ import annotations

import unicodedata

import pandas as pd

from utils.projets import REGIONS_PRIORITAIRES, STATUTS_A_RELANCER, MOTIF_NON_RENSEIGNE

PRIORITE_ORDER = {"Haute": 0, "Moyenne": 1, "Info": 2}


def _normalise(texte) -> str:
    """Retire les accents et met en minuscule — nécessaire car le classeur
    orthographie parfois « Extrême-Nord » et parfois « Extreme-Nord » selon
    la feuille (observé entre « Données sites » et la table RH du Dashboard).
    Comparaison uniquement, jamais utilisé pour afficher un texte."""
    if texte is None:
        return ""
    s = unicodedata.normalize("NFKD", str(texte))
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


_REGIONS_PRIORITAIRES_NORM = {_normalise(r) for r in REGIONS_PRIORITAIRES}


def _zone_est_prioritaire(texte: str) -> bool:
    """Un texte de zone (région, nomenclature RH, nom d'équipe...) est
    considéré prioritaire s'il contient l'un des noms normalisés NOSO /
    Extrême-Nord — tolère les variantes orthographiques du classeur."""
    n = _normalise(texte)
    return any(r in n for r in _REGIONS_PRIORITAIRES_NORM)


def _reco(priorite: str, categorie: str, titre: str, detail: str, source: str) -> dict:
    return {"priorite": priorite, "categorie": categorie, "titre": titre, "detail": detail, "source": source}


# ---------------------------------------------------------------------------
# Règle 1 — Plan d'action RH déjà calculé dans le classeur (Dashboard,
# section « Plan d'action prioritaire »), avec priorité renforcée pour les
# équipes situées en région prioritaire (NOSO / Extrême-Nord).
# ---------------------------------------------------------------------------
def _regle_plan_action(data, top_n: int = 8) -> list[dict]:
    out = []
    ap = data.action_plan
    if ap is None or ap.empty or "Postes manquants" not in ap.columns:
        return out
    ap = ap.sort_values("Postes manquants", ascending=False).head(top_n)
    for _, row in ap.iterrows():
        zone = str(row.get("Équipe (antenne — zone)", "—"))
        manques = row.get("Postes manquants", "—")
        profils = row.get("Profils manquants", "—")
        recommandation = row.get("Recommandation", "—")
        prioritaire = _zone_est_prioritaire(zone)
        out.append(_reco(
            "Haute" if prioritaire else ("Moyenne" if manques and manques != 0 else "Info"),
            "Réactivité des agents (RH)",
            f"{zone} — {manques} poste(s) manquant(s)" + (" · région prioritaire 🔶" if prioritaire else ""),
            f"Profils manquants : {profils}. Recommandation (plan d'action du classeur AER) : {recommandation}",
            "Feuille Dashboard — Plan d'action prioritaire (classeur AER)",
        ))
    return out


# ---------------------------------------------------------------------------
# Règle 2 — Manques RH par région (table RH du Dashboard), avec priorité
# renforcée pour les régions NOSO / Extrême-Nord.
# ---------------------------------------------------------------------------
def _regle_manques_par_region(data) -> list[dict]:
    out = []
    rh = data.rh_table
    if rh is None or rh.empty:
        return out
    col_zone = rh.columns[0]
    for _, row in rh.iterrows():
        zone = str(row.get(col_zone, "—"))
        if zone.upper().startswith("TOTAL"):
            continue
        manques = row.get("Total manques")
        if manques is None or pd.isna(manques) or manques == 0:
            continue
        prioritaire = _zone_est_prioritaire(zone)
        if not prioritaire:
            continue  # cette règle ne sert qu'à mettre en avant les régions en crise
        pourvus = row.get("Postes pourvus", "—")
        out.append(_reco(
            "Haute", "Relance régionale (NOSO / Extrême-Nord)",
            f"{zone} — {int(manques)} poste(s) manquant(s) (pourvus : {pourvus}) 🔶",
            "Région en crise explicitement ciblée pour la relance : le déficit RH ici freine directement "
            "la capacité à reprendre ou relancer des projets d'électrification dans cette zone.",
            "Feuille Dashboard — table des manques RH par antenne/région (classeur AER)",
        ))
    return out


# ---------------------------------------------------------------------------
# Règle 3 — Charge relative (sites / agent) par antenne : repère les
# antennes objectivement les plus chargées, donc les plus susceptibles
# d'avoir des délais d'intervention allongés.
# ---------------------------------------------------------------------------
def _regle_charge_antennes(data, seuil_ratio_haut: float = 8.0) -> list[dict]:
    out = []
    det = data.antennes_detail
    if det is None or det.empty or "Sites par agent" not in det.columns:
        return out
    surcharge = det[det["Sites par agent"] >= seuil_ratio_haut].sort_values("Sites par agent", ascending=False)
    for _, row in surcharge.iterrows():
        antenne = str(row.get("Antenne", "—"))
        ratio = row.get("Sites par agent")
        couverture = row.get("Régions / départements couverts", "—")
        prioritaire = _zone_est_prioritaire(couverture) or _zone_est_prioritaire(antenne)
        out.append(_reco(
            "Haute" if prioritaire else "Moyenne",
            "Réactivité des agents (charge)",
            f"{antenne} — charge de {ratio:.1f} sites/agent" + (" · couvre une région prioritaire 🔶" if prioritaire else ""),
            f"Couvre : {couverture}. Une charge élevée allonge mécaniquement le délai moyen entre deux "
            "visites d'un même site — cibler cette antenne en priorité pour un renfort ou un redéploiement "
            "améliore directement la réactivité de terrain.",
            "Feuille Antennes — Détail solaire (classeur AER), colonne « Sites par agent »",
        ))
    return out


# ---------------------------------------------------------------------------
# Règle 4 — Registre de suivi de projets (saisi par l'utilisateur) : projets
# suspendus/planifiés à relancer, priorité renforcée en région NOSO /
# Extrême-Nord et pour les blocages les plus anciens.
# ---------------------------------------------------------------------------
def _regle_projets_a_relancer(projets_view: pd.DataFrame, top_n: int = 10) -> list[dict]:
    out = []
    if projets_view is None or projets_view.empty:
        return [_reco(
            "Info", "Suivi de projets",
            "Aucun projet saisi dans le registre de suivi",
            "La page « Suivi de projets » permet d'enregistrer l'avancement réel (planifié / en cours / "
            "suspendu / repris / terminé) de chaque site. Sans saisie, cette absence d'alerte ne signifie "
            "pas qu'aucun projet n'est à l'arrêt — seulement que rien n'a encore été renseigné.",
            "Registre de suivi de projets (vide)",
        )]

    a_relancer = projets_view[projets_view["Statut"].isin(STATUTS_A_RELANCER)].copy()
    if a_relancer.empty:
        return [_reco(
            "Info", "Suivi de projets",
            "Aucun projet suspendu ou planifié en attente dans le registre",
            f"{len(projets_view)} projet(s) suivi(s) au total, aucun avec un statut « Suspendu » ou « Planifié ».",
            "Registre de suivi de projets",
        )]

    a_relancer["_prioritaire"] = a_relancer["Région prioritaire (NOSO / Extrême-Nord)"] == "Oui"
    a_relancer = a_relancer.sort_values(["_prioritaire", "Jours depuis dernier mouvement"],
                                         ascending=[False, False]).head(top_n)
    for _, row in a_relancer.iterrows():
        site = row.get("Site", "—")
        region = row.get("Région", "—")
        statut = row.get("Statut", "—")
        jours = row.get("Jours depuis dernier mouvement")
        jours_txt = f"{int(jours)} jour(s)" if pd.notna(jours) else "inconnu"
        motif_brut = row.get("Motif de blocage")
        motif = motif_brut if motif_brut and motif_brut != MOTIF_NON_RENSEIGNE else "non renseigné"
        prioritaire = bool(row.get("_prioritaire"))
        out.append(_reco(
            "Haute" if prioritaire else "Moyenne",
            "Reprise de projets" if statut == "Suspendu" else "Suivi de projets",
            f"{site} ({region}) — {statut} depuis {jours_txt}" + (" · région prioritaire 🔶" if prioritaire else ""),
            f"Motif de blocage déclaré : {motif}. Responsable désigné : {row.get('Responsable désigné') or '—'}.",
            "Registre de suivi de projets (saisi par l'utilisateur)",
        ))
    return out


# ---------------------------------------------------------------------------
# Règle 5 — Fonds revolving : délégations avec un taux de recouvrement bas
# ou des dossiers en litige, comme indicateur de suivi des agents de ce
# mécanisme distinct (frais de raccordement ENEO, pas le parc solaire).
# ---------------------------------------------------------------------------
def _regle_fonds_revolving(revolving_view: pd.DataFrame, seuil_taux_bas: float = 50.0) -> list[dict]:
    out = []
    if revolving_view is None or revolving_view.empty:
        return out
    if "Montant à rembourser (FCFA)" not in revolving_view.columns:
        return out
    by_region = revolving_view.groupby("Délégation régionale", as_index=False).agg(
        a_rembourser=("Montant à rembourser (FCFA)", "sum"),
        rembourse=("Montant remboursé à ce jour (FCFA)", "sum"),
        dossiers=("N° dossier", "count"),
    )
    by_region = by_region[by_region["a_rembourser"] > 0]
    by_region["taux"] = (by_region["rembourse"] / by_region["a_rembourser"] * 100).round(1)
    bas = by_region[by_region["taux"] < seuil_taux_bas].sort_values("taux")
    for _, row in bas.iterrows():
        deleg = row["Délégation régionale"]
        prioritaire = _zone_est_prioritaire(deleg)
        out.append(_reco(
            "Moyenne", "Fonds revolving (suivi des agents)",
            f"Délégation {deleg} — taux de recouvrement de {row['taux']:.1f} %"
            + (" · couvre une région prioritaire 🔶" if prioritaire else ""),
            f"{int(row['dossiers'])} dossier(s) suivi(s). Un taux bas peut signaler un besoin de relance des "
            "ménages par les agents de suivi de cette délégation — mécanisme distinct du parc solaire "
            "(frais de raccordement ENEO), mais même logique de réactivité d'agent.",
            "Registre du Fonds revolving (saisi par l'utilisateur)",
        ))
    return out


def generate_recommendations(data, projets_view: pd.DataFrame, revolving_view: pd.DataFrame | None = None) -> list[dict]:
    """Point d'entrée unique : assemble toutes les règles et trie par
    priorité (Haute > Moyenne > Info). Ne lève jamais d'exception sur des
    données manquantes — chaque règle se neutralise silencieusement si sa
    source n'est pas disponible."""
    recos: list[dict] = []
    recos += _regle_plan_action(data)
    recos += _regle_manques_par_region(data)
    recos += _regle_charge_antennes(data)
    recos += _regle_projets_a_relancer(projets_view)
    recos += _regle_fonds_revolving(revolving_view)
    recos.sort(key=lambda r: PRIORITE_ORDER.get(r["priorite"], 9))
    return recos


def explain_rules() -> list[tuple[str, str]]:
    """Description des règles pour l'encadré de transparence de la page —
    chaque recommandation affichée peut être reliée à l'une de ces règles."""
    return [
        ("Plan d'action RH (classeur)", "Reprend le plan d'action déjà calculé dans le classeur AER "
         "(feuille Dashboard), en mettant en évidence les équipes des régions NOSO / Extrême-Nord."),
        ("Manques RH par région", "Signale les régions NOSO / Extrême-Nord où des postes RH manquent, "
         "frein direct à la relance de projets dans ces zones."),
        ("Charge par antenne (sites/agent)", "Repère les antennes dont le ratio sites/agent est élevé "
         "(≥ 8 par défaut) — indicateur objectif de risque de délai d'intervention allongé."),
        ("Projets à relancer", "Lit le registre de suivi de projets (page « Suivi de projets ») et priorise "
         "les projets suspendus/planifiés les plus anciens, région prioritaire en tête."),
        ("Fonds revolving", "Signale les délégations du Fonds revolving avec un taux de recouvrement bas, "
         "à partir du registre saisi sur la page « Fonds revolving »."),
    ]
