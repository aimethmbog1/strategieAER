"""Contenu initial NON SENSIBLE du module Data Center, tiré des documents de la SDMSE :
cartographie réseau, fiche d'audit des serveurs (25/10/2026), maintenance courante du réseau,
rapport de test des batteries UPS (13/07/2026). Adressage IP, comptes et constats de sécurité
ne figurent pas ici : ils sont importés en base (voir imports.py)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .regles import Seuil

SRC_CARTO = "Cartographie réseau du Data Center"
SRC_AUDIT = "Fiche d'audit serveurs (25/10/2026)"
SRC_UPS = "Rapport de test des batteries UPS (13/07/2026)"
SRC_FM800 = "Documentation Huawei FusionModule800"

SALLES = [
    {"nom": "Salle des serveurs", "description": "Héberge le micro-module Huawei FusionModule800."},
    {"nom": "Salle des écrans", "description": "Salle de supervision (citée dans le rapport de test des batteries)."},
]

S = "Salle des serveurs"
# Équipements : (code, désignation, système, type_controle, fabricant, modèle, quantité, criticité, redondance,
#                point unique, puissance W, à compléter, source, extra)
_E = [
    # --- FusionModule800 et infrastructure
    ("FM800", "Micro-module Huawei FusionModule800", "Environnement", "SALLE", "Huawei", "FusionModule800", 1,
     "Critique", "—", "Non", None, "Nombre de baies, configuration (BC), date de mise en service", SRC_FM800, {}),
    ("FM800-UPS", "Onduleur intégré au FusionModule800", "Alimentation électrique", None, "Huawei", "UPS2000G", 1,
     "Critique", "À confirmer (N, N+1 ou 2N)", "À confirmer", None, "Puissance (kVA), configuration de redondance",
     SRC_UPS, {}),
    ("FM800-BATT", "Batteries de l'onduleur — 4 packs lithium (LiFePO4)", "Alimentation électrique", None, "Huawei",
     "ESS-240V12-9AhBPVBA04", 4, "Critique", "4 packs en parallèle (240 V, 36 Ah, 8 640 Wh)", "Non", None, "",
     SRC_UPS, {"numero_serie": "2102313SBABNRA100026", "date_mes": datetime(2026, 5, 7),
               "observations": "Test d'autonomie du 13/07/2026 : 90 min de 100 % à 10 % sous environ 5,2 kW, sans alarme."}),
    ("FM800-CLIM", "Climatisation intégrée (détente directe, en rangée)", "Refroidissement", None, "Huawei", "", 1,
     "Critique", "À confirmer (N ou N+1)", "À confirmer", None, "Nombre d'unités, modèle, puissance frigorifique", SRC_FM800, {}),
    ("FM800-PDU", "Distribution électrique des baies (PDU)", "Alimentation électrique", None, "Huawei", "", 1,
     "Critique", "À confirmer", "À confirmer", None, "Nombre et modèle des PDU / rPDU", SRC_FM800, {}),
    ("FM800-ECC800", "Automate de supervision ECC800", "Supervision", None, "Huawei", "ECC800", 1,
     "Haute", "—", "Non", None, "Version logicielle, mode d'accès", SRC_FM800, {}),
    ("FM800-CAPTEURS", "Capteurs : température / humidité, fuite d'eau, contacts de porte", "Supervision", None,
     "Huawei", "", 1, "Haute", "—", "Non", None, "Nombre et emplacement des capteurs", SRC_FM800, {}),
    ("FM800-EXTINCTION", "Système de détection / extinction incendie", "Détection et extinction incendie", None,
     "", "", 1, "Critique", "—", "À confirmer", None, "Présence (option du FM800), type d'agent, date de la dernière vérification",
     SRC_FM800, {"etat": "À confirmer"}),
    ("GE-01", "Groupe électrogène de secours", "Alimentation électrique", None, "", "", 1, "Critique", "—", "Oui",
     None, "Marque, puissance (kVA), inverseur de source (ATS), autonomie carburant", SRC_UPS, {}),
    # --- Réseau
    ("CORE_AR2240-01", "Routeur de bordure WAN n°1 (accès Internet MTN)", "Réseau", "RESEAU", "Huawei", "AR2240-C", 1,
     "Critique", "Deux accès Internet indépendants", "Non", 150, "", SRC_CARTO, {"alias": "view", "version": "V200R009C00SPC500"}),
    ("CORE_AR2240-02", "Routeur de bordure WAN n°2 (accès Internet MTN)", "Réseau", "RESEAU", "Huawei", "AR2240-C", 1,
     "Critique", "Deux accès Internet indépendants", "Non", 150, "", SRC_CARTO, {"version": "V200R009C00SPC500"}),
    ("CORE_USG6620-01", "Pare-feu n°1 (HRP Master)", "Réseau", "RESEAU", "Huawei", "USG6620", 1, "Critique",
     "Grappe actif / passif (HRP) avec USG6620-02", "Non", 120, "", SRC_CARTO, {"version": "V500R001C60SPC500"}),
    ("CORE_USG6620-02", "Pare-feu n°2 (HRP Standby)", "Réseau", "RESEAU", "Huawei", "USG6620", 1, "Critique",
     "Grappe actif / passif (HRP) avec USG6620-01", "Non", 120, "", SRC_CARTO, {"version": "V500R001C60SPC500"}),
    ("Cameroon_Core_5720CSS", "Commutateur cœur (pile CSS de deux unités)", "Réseau", "RESEAU", "Huawei", "S5720", 2,
     "Critique", "Pile de deux unités (CSS)", "À confirmer", 40, "", SRC_CARTO, {"version": "V200R010C00SPC600"}),
    ("LSW_Maintenance-02", "Commutateur d'accès du réseau de maintenance", "Réseau", "RESEAU", "Huawei", "S2700/S3700", 1,
     "Moyenne", "—", "Oui", None, "Modèle exact", SRC_CARTO, {"alias": "Minee_Maintenance", "version": "V100R006C05"}),
    ("CE6881-01", "Commutateur Data Center n°1", "Réseau", "RESEAU", "Huawei", "CE6881-48T6CQ-B", 1, "Haute",
     "Paire avec CE6881-02", "Non", 194, "Nom d'hôte, rôle, liste de contrôle à valider", SRC_UPS, {}),
    ("CE6881-02", "Commutateur Data Center n°2", "Réseau", "RESEAU", "Huawei", "CE6881-48T6CQ-B", 1, "Haute",
     "Paire avec CE6881-01", "Non", 194, "Nom d'hôte, rôle, liste de contrôle à valider", SRC_UPS, {}),
    ("SAN-SNS2624", "Commutateur SAN (Fibre Channel)", "Serveurs et stockage", None, "Huawei", "SNS2624", 1, "Haute",
     "—", "À confirmer", 76, "Liste de contrôle à créer", SRC_UPS, {}),
    # --- Serveurs
    ("TESTSERVER", "Serveur de test (JBoss, Oracle autonome, Redis)", "Serveurs et stockage", None, "Huawei", "2288H V5", 1,
     "Moyenne", "—", "Non", 350, "", SRC_AUDIT, {"version": "SLES 11 SP3"}),
    ("DBSERVER1", "Serveur de base de données — nœud 1 de la grappe Oracle RAC", "Serveurs et stockage", None, "Huawei",
     "2288H V5", 1, "Critique", "Grappe Oracle RAC à deux nœuds", "Non", 350, "", SRC_AUDIT,
     {"alias": "dbserver1", "version": "SLES 11 SP3 · Oracle 11gR2 RAC"}),
    ("DBSERVER2", "Serveur de base de données — nœud 2 de la grappe Oracle RAC", "Serveurs et stockage", None, "Huawei",
     "2288H V5", 1, "Critique", "Grappe Oracle RAC à deux nœuds", "Non", 350, "", SRC_AUDIT,
     {"alias": "dbserver2", "version": "SLES 11 SP3 · Oracle 11gR2 RAC"}),
    ("V-INTERFACE1", "Serveur d'application n°1 (EagleWiz FKM, JBoss, Nginx)", "Serveurs et stockage", None, "Huawei",
     "2288H V5", 1, "Critique", "Actif / actif avec V-INTERFACE2", "Non", 350, "", SRC_AUDIT, {"version": "SLES 11 SP3"}),
    ("V-INTERFACE2", "Serveur d'application n°2 (JBoss, Nginx)", "Serveurs et stockage", None, "Huawei", "2288H V5", 1,
     "Critique", "Actif / actif avec V-INTERFACE1", "Non", 350, "", SRC_AUDIT, {"version": "SLES 11 SP3"}),
    ("SERVEUR-06", "Serveur 2288H V5 non identifié n°1", "Serveurs et stockage", None, "Huawei", "2288H V5", 1,
     "Moyenne", "—", "À confirmer", 350, "Nom d'hôte, rôle, liste de contrôle à créer", SRC_UPS, {"etat": "À confirmer"}),
    ("SERVEUR-07", "Serveur 2288H V5 non identifié n°2", "Serveurs et stockage", None, "Huawei", "2288H V5", 1,
     "Moyenne", "—", "À confirmer", 350, "Nom d'hôte, rôle, liste de contrôle à créer", SRC_UPS, {"etat": "À confirmer"}),
    # --- Stockage et sauvegarde
    ("DORADO-3000V6", "Baie de stockage flash (LUN de la grappe Oracle via UltraPath)", "Serveurs et stockage", None,
     "Huawei", "OceanStor Dorado 3000 V6", 1, "Critique", "4 chemins par LUN", "À confirmer", 700, "", SRC_AUDIT, {}),
    ("OCEANSTOR-5500V5", "Baie de stockage", "Serveurs et stockage", None, "Huawei", "OceanStor 5500 V5", 1, "Haute",
     "—", "À confirmer", 1000, "Usage, liste de contrôle à créer", SRC_UPS, {}),
    ("OCEANPROTECT-X3000", "Appliance de sauvegarde", "Serveurs et stockage", None, "Huawei", "OceanProtect X3000", 1,
     "Haute", "—", "Oui", 500, "Politique de sauvegarde, liste de contrôle à créer", SRC_UPS, {}),
]

EQUIPEMENTS = []
for (code, des, sysm, tc, fab, mod, q, crit, red, spof, pw, manq, src, extra) in _E:
    EQUIPEMENTS.append({"code": code, "designation": des, "systeme": sysm, "type_controle": tc, "fabricant": fab,
                        "modele": mod, "quantite": q, "criticite": crit, "redondance": red, "point_unique": spof,
                        "puissance_w": pw, "a_completer": manq or None, "source": src, "salle": S,
                        "etat": "En service", **extra})

SEUILS = [
    Seuil("temp_c", "Température à l'entrée d'air des baies", "°C", avert_min=18, avert_max=27, crit_max=32,
          reference="ASHRAE TC 9.9 (plage recommandée 18–27 °C, classe A1 jusqu'à 32 °C) ; fiche Huawei FusionModule800 "
                    "(18–27 °C recommandé, 32 °C au plus)"),
    Seuil("hr_pct", "Humidité relative", "%", avert_min=20, avert_max=60, crit_max=80,
          reference="ASHRAE TC 9.9 (≤ 60 % HR, point de rosée ≤ 15 °C) ; fiche Huawei FusionModule800 (20–80 % HR)"),
    Seuil("disque_pct", "Taux d'occupation disque / groupe ASM", "%", avert_max=80, crit_max=90,
          reference="Fiche d'audit serveurs (au-delà de 80 % à signaler)"),
    Seuil("sauvegarde_h", "Âge de la dernière sauvegarde", "h", avert_max=24, crit_max=48,
          reference="Fiche d'audit serveurs (au-delà de 48 h à signaler)"),
    Seuil("horloge_s", "Écart d'horloge avec les autres équipements", "s", avert_max=5, crit_max=60,
          reference="Fiche d'audit serveurs (écart supérieur à 5 s à signaler) ; même source de temps NTP"),
    Seuil("sessions_oracle", "Sessions sur l'instance Oracle", "", avert_max=800, crit_max=1400,
          reference="Fiche d'audit serveurs (> 800 à signaler ; limite paramétrée sessions = 1 536)"),
    Seuil("terre_ohm", "Résistance de terre (raccordement sur barre de terre)", "Ω", crit_max=5,
          reference="Maintenance courante système réseau (< 5 Ω sur barre de terre, < 10 Ω sur prise de terre)"),
    Seuil("ups_charge_pct", "Taux de charge de l'onduleur", "%", avert_max=80, crit_max=90,
          reference="Bonne pratique d'exploitation (à valider ; ramener à 40 / 50 % par onduleur en configuration 2N)"),
]

# Contrôles dont le résultat est une mesure chiffrée évaluée par un seuil
def _grandeur(c: dict) -> str | None:
    cmd, pt = c.get("commande", ""), c.get("point", "")
    if cmd.startswith("df -h") or cmd.startswith("asmcmd lsdg"):
        return "disque_pct"
    if cmd.startswith("rman"):
        return "sauvegarde_h"
    if cmd.strip() == "date":
        return "horloge_s"
    if "v\\$session" in cmd or "v$session" in cmd:
        return "sessions_oracle"
    if pt.startswith("Température de la salle"):
        return "temp_c"
    if pt.startswith("Humidité de la salle"):
        return "hr_pct"
    if pt.startswith("Conformité de la mise à la terre"):
        return "terre_ohm"
    return None


def controles() -> list[dict]:
    brut = json.loads((Path(__file__).parent / "donnees" / "controles.json").read_text(encoding="utf-8"))
    return [{**c, "grandeur": _grandeur(c)} for c in brut]
