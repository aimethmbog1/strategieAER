"""Règles métier du module Data Center : fonctions pures, sans accès à la base ni à l'interface (testées)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

ORDRE = {"OK": 0, "Information": 1, "Avertissement": 2, "Critique": 3}
JOURS_FREQUENCE = {"Journalier": 1, "Hebdomadaire": 7, "Mensuel": 30, "Trimestriel": 91, "Semestriel": 182, "Annuel": 365}


@dataclass(frozen=True)
class Seuil:
    grandeur: str
    libelle: str
    unite: str = ""
    avert_min: float | None = None
    avert_max: float | None = None
    crit_min: float | None = None
    crit_max: float | None = None
    reference: str = ""


def evaluer_mesure(valeur: float | None, s: Seuil | None) -> str:
    """Sévérité d'une mesure : « Critique » si hors seuil critique, « Avertissement » si hors seuil
    d'avertissement, « OK » sinon (ou si la valeur / le seuil manquent)."""
    if valeur is None or s is None:
        return "OK"
    if (s.crit_max is not None and valeur > s.crit_max) or (s.crit_min is not None and valeur < s.crit_min):
        return "Critique"
    if (s.avert_max is not None and valeur > s.avert_max) or (s.avert_min is not None and valeur < s.avert_min):
        return "Avertissement"
    return "OK"


def evaluer_releve(statut: str | None, valeur: float | None, s: Seuil | None, criticite: str = "Moyenne") -> str:
    """Sévérité d'un relevé d'inspection.

    - Une mesure chiffrée est évaluée par rapport à son seuil.
    - Un contrôle « Non conforme » est un avertissement, et devient critique sur un équipement critique.
    - « Conforme » et « S.O. » ne créent pas d'écart.
    La sévérité retenue est la plus grave des deux évaluations.
    """
    sev = evaluer_mesure(valeur, s)
    if statut == "Non conforme":
        sev_statut = "Critique" if criticite == "Critique" else "Avertissement"
        sev = max(sev, sev_statut, key=ORDRE.get)
    return sev


def pire(severites) -> str:
    sev = [x for x in severites if x in ORDRE]
    return max(sev, key=ORDRE.get) if sev else "OK"


def prochaine_echeance(derniere: datetime | None, frequence: str) -> datetime | None:
    """Date à laquelle le contrôle doit être refait ; None si jamais réalisé (donc dû immédiatement)."""
    if derniere is None:
        return None
    return derniere + timedelta(days=JOURS_FREQUENCE.get(frequence, 30))


def est_en_retard(derniere: datetime | None, frequence: str, maintenant: datetime) -> bool:
    """Un contrôle journalier est en retard s'il n'a pas été fait aujourd'hui ; les autres, si leur
    échéance (dernière réalisation + période) est dépassée. Jamais réalisé = en retard."""
    if derniere is None:
        return True
    if frequence == "Journalier":
        return derniere.date() < maintenant.date()
    return prochaine_echeance(derniere, frequence) < maintenant


@dataclass(frozen=True)
class RegleEscalade:
    severite: str
    delai_min: int
    destinataire: str


ESCALADE_DEFAUT = [
    RegleEscalade("Avertissement", 240, "Responsable du Data Center"),
    RegleEscalade("Critique", 15, "Responsable du Data Center"),
    RegleEscalade("Critique", 30, "Sous-directeur, puis Direction"),
]


def niveau_escalade(severite: str, emise: datetime, acquittee: datetime | None, maintenant: datetime,
                    regles=ESCALADE_DEFAUT) -> list[RegleEscalade]:
    """Règles d'escalade déclenchées pour une alerte : celles de sa sévérité dont le délai est écoulé
    sans acquittement. Une alerte acquittée n'est plus escaladée."""
    if acquittee is not None:
        return []
    ecoule = (maintenant - emise).total_seconds() / 60
    return [r for r in regles if r.severite == severite and ecoule >= r.delai_min]


def taux_conformite(severites) -> float | None:
    """Part des relevés sans écart (en %)."""
    sev = list(severites)
    return None if not sev else round(100 * sum(1 for s in sev if s == "OK") / len(sev), 1)


def taux_respect_plan(nb_controles: int, nb_en_retard: int) -> float | None:
    """Part des contrôles réalisés dans les délais (en %)."""
    return None if nb_controles == 0 else round(100 * (nb_controles - nb_en_retard) / nb_controles, 1)


def autonomie_estimee_min(energie_wh: float, charge_w: float, profondeur: float = 0.9, rendement: float = 0.92) -> float | None:
    """Autonomie théorique d'un onduleur : énergie utile des batteries × rendement / charge.
    Ex. 8 640 Wh × 0,9 × 0,92 / 4 800 W ≈ 89 min."""
    if not charge_w or charge_w <= 0:
        return None
    return round(60 * energie_wh * profondeur * rendement / charge_w, 0)
