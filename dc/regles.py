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


# ============================================================================= lot 2 : alertes et escalade
@dataclass(frozen=True)
class Palier:
    """Palier d'escalade : passé `delai_min` minutes sans acquittement, les contacts du `niveau` sont notifiés."""
    severite: str
    delai_min: int
    niveau: int


# Délais validés le 11/11/2026 : critique 15 min puis 30 min ; avertissement 4 h. Le niveau 1 est notifié à l'émission.
PALIERS_DEFAUT = [
    Palier("Critique", 0, 1), Palier("Critique", 15, 2), Palier("Critique", 30, 3),
    Palier("Avertissement", 0, 1), Palier("Avertissement", 240, 2),
]


def paliers_dus(severite: str, emise: datetime, acquittee: datetime | None, resolue: datetime | None,
                maintenant: datetime, deja_notifie: int = 0, paliers=PALIERS_DEFAUT) -> list[Palier]:
    """Paliers à notifier maintenant : ceux de la sévérité dont le délai est écoulé et dont le niveau n'a pas
    encore été notifié. Une alerte acquittée ou résolue n'est plus escaladée."""
    if acquittee is not None or resolue is not None:
        return []
    ecoule = (maintenant - emise).total_seconds() / 60
    dus = [p for p in paliers if p.severite == severite and ecoule >= p.delai_min and p.niveau > (deja_notifie or 0)]
    return sorted(dus, key=lambda p: p.niveau)


def prochain_palier(severite: str, emise: datetime, deja_notifie: int = 0, paliers=PALIERS_DEFAUT) -> tuple[Palier, datetime] | None:
    """Prochain palier non encore notifié et son heure de déclenchement (None s'il n'en reste pas)."""
    suivants = sorted((p for p in paliers if p.severite == severite and p.niveau > (deja_notifie or 0)),
                      key=lambda p: p.niveau)
    if not suivants:
        return None
    return suivants[0], emise + timedelta(minutes=suivants[0].delai_min)


def destinataire_concerne(niveau_contact: int | None, severite_min: str | None, systeme_contact: str | None,
                          actif: bool, niveau: int, severite: str, systeme: str | None) -> bool:
    """Un contact reçoit la notification d'un palier s'il est actif, rattaché à ce niveau, si la sévérité atteint
    son seuil personnel et si l'alerte concerne son système (« Tous » ou vide = tous les systèmes)."""
    if not actif or (niveau_contact or 0) != niveau:
        return False
    if ORDRE.get(severite, 0) < ORDRE.get(severite_min or "Avertissement", 2):
        return False
    return (systeme_contact or "Tous") == "Tous" or systeme is None or systeme_contact == systeme


def severite_alerte_fusion(actuelle: str, nouvelle: str) -> str:
    """Une alerte ouverte ne peut que s'aggraver : on retient la plus grave des deux sévérités."""
    return max(actuelle, nouvelle, key=lambda x: ORDRE.get(x, 0))


def delai_moyen_min(debuts, fins) -> float | None:
    """Moyenne (en minutes) des délais entre deux séries d'horodatages ; les couples incomplets sont ignorés.
    Sert au délai moyen d'acquittement et au délai moyen de résolution."""
    d = [(f - a).total_seconds() / 60 for a, f in zip(debuts, fins) if a is not None and f is not None and f >= a]
    return None if not d else round(sum(d) / len(d), 1)


def format_duree(minutes: float | None) -> str:
    """Durée lisible : « 12 min », « 3 h 05 », « 2 j 4 h »."""
    if minutes is None:
        return "—"
    m = int(round(minutes))
    if m < 60:
        return f"{m} min"
    if m < 1440:
        return f"{m // 60} h {m % 60:02d}"
    return f"{m // 1440} j {(m % 1440) // 60} h"
