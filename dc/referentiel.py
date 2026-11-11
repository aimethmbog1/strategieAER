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
SRC_PLAN = "Plan des baies du FusionModule800 (A1, A2, A3)"

BAIES = [
    {"nom": "A1", "position": "IT Cabinet 01 — 42U", "salle": S},
    {"nom": "A2", "position": "Converged Cabinet (armoire d'infrastructure) — 42U", "salle": S},
    {"nom": "A3", "position": "IT Cabinet 02 — 42U", "salle": S},
]
HAUTEUR_BAIE_U = 42

# Équipements : (code, désignation, système, type_controle, fabricant, modèle, quantité, criticité, redondance,
#                point unique, puissance W, à compléter, source, baie, U début, U fin, extra)
_E = [
    # --- FusionModule800 : armoire d'infrastructure A2
    ("FM800", "Micro-module Huawei FusionModule800 (baies A1, A2, A3)", "Environnement", "SALLE", "Huawei",
     "FusionModule800", 1, "Critique", "—", "Non", None, "Configuration (BC), date de mise en service", SRC_PLAN,
     None, None, None, {}),
    ("FM800-INDICATEUR", "Module de signalisation (indicator module)", "Supervision", None, "Huawei", "", 1, "Basse",
     "—", "Non", None, None, SRC_PLAN, "A2", 42, 42, {}),
    ("FM800-PDU", "Module de distribution électrique (power distribution module)", "Alimentation électrique", None,
     "Huawei", "", 1, "Critique", "—", "Oui", None, "Modèle, calibres des départs, PDU de baie (rPDU)", SRC_PLAN,
     "A2", 30, 32, {}),
    ("FM800-UPS", "Onduleur intégré au FusionModule800", "Alimentation électrique", None, "Huawei", "UPS2000-G", 1,
     "Critique", "Onduleur unique (pas de second onduleur sur le plan des baies)", "Oui", None, "Puissance (kVA)",
     SRC_PLAN, "A2", 28, 29, {}),
    ("FM800-ECC800", "Automate de supervision ECC800", "Supervision", None, "Huawei", "ECC800", 1,
     "Haute", "—", "Non", None, "Version logicielle, mode d'accès", SRC_PLAN, "A2", 23, 23, {}),
    ("FM800-AC1", "Climatiseur n°1 — unité intérieure en rangée", "Refroidissement", None, "Huawei", "",
     1, "Critique", "2 unités (AC1, AC2) : N+1 à confirmer", "Non", None,
     "Modèle, puissance frigorifique, unité extérieure", SRC_PLAN, "A2", 1, 10, {}),
    ("FM800-AC2", "Climatiseur n°2 — unité intérieure en rangée", "Refroidissement", None, "Huawei", "",
     1, "Critique", "2 unités (AC1, AC2) : N+1 à confirmer", "Non", None,
     "Modèle, puissance frigorifique, unité extérieure", SRC_PLAN, "A2", 11, 20, {}),
    ("FM800-AC2-CTRL", "Contrôleur du climatiseur n°2", "Refroidissement", None, "Huawei", "", 1, "Haute", "—", "Non",
     None, None, SRC_PLAN, "A2", 21, 21, {}),
    ("FM800-AC1-CTRL", "Contrôleur du climatiseur n°1", "Refroidissement", None, "Huawei", "", 1, "Haute", "—", "Non",
     None, None, SRC_PLAN, "A2", 22, 22, {}),
    ("FM800-CAPTEURS", "Capteurs : température / humidité, fuite d'eau, contacts de porte", "Supervision", None,
     "Huawei", "", 1, "Haute", "—", "Non", None, "Nombre et emplacement des capteurs", SRC_FM800, None, None, None, {}),
    ("FM800-EXTINCTION", "Système de détection / extinction incendie", "Détection et extinction incendie", None,
     "", "", 1, "Critique", "—", "À confirmer", None,
     "Présence (option du FM800, absente du plan des baies), type d'agent, dernière vérification", SRC_FM800,
     None, None, None, {"etat": "À confirmer"}),
    ("FM800-BATT", "Batteries de l'onduleur — 4 packs lithium (LiFePO4)", "Alimentation électrique", None, "Huawei",
     "ESS-240V12-9AhBPVBA04", 4, "Critique", "4 packs en parallèle (240 V, 36 Ah, 8 640 Wh)", "Non", None, None,
     SRC_UPS, "A3", 1, 8,
     {"numero_serie": "2102313SBABNRA100026", "date_mes": datetime(2026, 5, 7),
      "observations": "Packs 1 à 4 en A3, U1 à U8. Test d'autonomie du 13/07/2026 : 90 min de 100 % à 10 % "
                      "sous environ 5,2 kW, sans alarme."}),
    ("GE-01", "Groupe électrogène de secours", "Alimentation électrique", None, "", "", 1, "Critique", "—", "Oui",
     None, "Marque, puissance (kVA), inverseur de source (ATS), autonomie carburant", SRC_UPS, None, None, None, {}),
    # --- Baie A1 : réseau et serveurs d'application
    ("CORE_AR2240-01", "Routeur de bordure WAN n°1 (accès Internet MTN)", "Réseau", "RESEAU", "Huawei", "AR2240-C", 1,
     "Critique", "Deux accès Internet indépendants", "Non", 150, None, SRC_CARTO, "A1", 39, 40,
     {"alias": "view ; AR2240-1", "version": "V200R009C00SPC500"}),
    ("CORE_AR2240-02", "Routeur de bordure WAN n°2 (accès Internet MTN)", "Réseau", "RESEAU", "Huawei", "AR2240-C", 1,
     "Critique", "Deux accès Internet indépendants", "Non", 150, None, SRC_CARTO, "A1", 36, 37,
     {"alias": "AR2240-2", "version": "V200R009C00SPC500"}),
    ("CORE_USG6620-01", "Pare-feu n°1 (HRP Master)", "Réseau", "RESEAU", "Huawei", "USG6620", 1, "Critique",
     "Grappe actif / passif (HRP) avec USG6620-02", "Non", 120, None, SRC_CARTO, "A1", 34, 34,
     {"alias": "USG6620-1", "version": "V500R001C60SPC500"}),
    ("CORE_USG6620-02", "Pare-feu n°2 (HRP Standby)", "Réseau", "RESEAU", "Huawei", "USG6620", 1, "Critique",
     "Grappe actif / passif (HRP) avec USG6620-01", "Non", 120, None, SRC_CARTO, "A1", 32, 32,
     {"alias": "USG6620-2", "version": "V500R001C60SPC500"}),
    ("Cameroon_Core_5720CSS", "Commutateur cœur (pile CSS de deux unités S5720-1 et S5720-2)", "Réseau", "RESEAU",
     "Huawei", "S5720", 2, "Critique", "Pile de deux unités (CSS)", "Non", 40, None, SRC_CARTO, "A1", 28, 30,
     {"alias": "S5720-1 ; S5720-2", "version": "V200R010C00SPC600",
      "observations": "S5720-1 en A1, U30 ; S5720-2 en A1, U28."}),
    ("LSW_Maintenance-02", "Commutateur d'accès du réseau de maintenance", "Réseau", "RESEAU", "Huawei", "S2700/S3700", 1,
     "Moyenne", "—", "Oui", None, "Modèle exact ; emplacement (absent du plan des baies)", SRC_CARTO, None, None, None,
     {"alias": "Minee_Maintenance", "version": "V100R006C05"}),
    ("KVM-A1", "Console KVM de la baie A1", "Supervision", None, "", "KVM", 1, "Basse", "—", "Non", None,
     "Marque, modèle", SRC_PLAN, "A1", 23, 23, {}),
    ("CE6881-01", "Commutateur Data Center n°1", "Réseau", "RESEAU", "Huawei", "CE6881-48T6CQ-B", 1, "Haute",
     "Paire avec CE6881-02", "Non", 194, "Nom d'hôte, rôle", SRC_PLAN, "A1", 20, 20, {"alias": "CE6881-48T6CQ-1"}),
    ("CE6881-02", "Commutateur Data Center n°2", "Réseau", "RESEAU", "Huawei", "CE6881-48T6CQ-B", 1, "Haute",
     "Paire avec CE6881-01", "Non", 194, "Nom d'hôte, rôle", SRC_PLAN, "A1", 18, 18, {"alias": "CE6881-48T6CQ-2"}),
    ("V-INTERFACE1", "Serveur d'application de vente n°1 (EagleWiz FKM, JBoss, Nginx)", "Serveurs et stockage", None,
     "Huawei", "2288H V5", 1, "Critique", "Actif / actif avec V-INTERFACE2", "Non", 350, None, SRC_AUDIT, "A1", 11, 12,
     {"alias": "Vending_Interface_1", "version": "SLES 11 SP3"}),
    ("V-INTERFACE2", "Serveur d'application de vente n°2 (JBoss, Nginx)", "Serveurs et stockage", None, "Huawei",
     "2288H V5", 1, "Critique", "Actif / actif avec V-INTERFACE1", "Non", 350, None, SRC_AUDIT, "A1", 8, 9,
     {"alias": "Vending_Interface_2", "version": "SLES 11 SP3"}),
    ("NETECO-SERVER", "Serveur de supervision NetEco (monitoring des centrales)", "Supervision", None, "Huawei",
     "RH2288H", 1, "Haute", "—", "Oui", 350, "Version NetEco, système d'exploitation, liste de contrôle à créer",
     SRC_PLAN, "A1", 5, 6, {}),
    ("TESTSERVER", "Serveur de test (JBoss, Oracle autonome, Redis)", "Serveurs et stockage", None, "Huawei",
     "2288H V5", 1, "Moyenne", "—", "Non", 350, None, SRC_AUDIT, "A1", 2, 3, {"version": "SLES 11 SP3"}),
    # --- Baie A3 : stockage, sauvegarde, bases de données
    ("OCEANPROTECT-X3000", "Appliance de sauvegarde (YDE_A3_OceanProtect_X3000)", "Serveurs et stockage", None,
     "Huawei", "OceanProtect X3000 V6", 1, "Haute", "—", "Oui", 500, "Politique de sauvegarde, liste de contrôle à créer",
     SRC_PLAN, "A3", 32, 33, {"alias": "YDE_A3_OceanProtect_X3000"}),
    ("DORADO-3000V6", "Baie de stockage flash (LUN de la grappe Oracle via UltraPath)", "Serveurs et stockage", None,
     "Huawei", "OceanStor Dorado 3000 V6", 1, "Critique", "4 chemins par LUN", "À confirmer", 700, None, SRC_AUDIT,
     "A3", 29, 30, {"alias": "MINEE_DC_Dorado"}),
    ("SNS2624-01", "Commutateur SAN Fibre Channel n°1", "Serveurs et stockage", None, "Huawei", "SNS2624", 1, "Haute",
     "Paire avec SNS2624-02", "Non", 76, "Liste de contrôle à créer", SRC_PLAN, "A3", 26, 26,
     {"alias": "SNS2624 FC Switch_1"}),
    ("SNS2624-02", "Commutateur SAN Fibre Channel n°2", "Serveurs et stockage", None, "Huawei", "SNS2624", 1, "Haute",
     "Paire avec SNS2624-01", "Non", 76, "Liste de contrôle à créer", SRC_PLAN, "A3", 24, 24,
     {"alias": "SNS2624 FC Switch_2"}),
    ("KVM-A3", "Console KVM de la baie A3", "Supervision", None, "", "KVM", 1, "Basse", "—", "Non", None,
     "Marque, modèle", SRC_PLAN, "A3", 22, 22, {}),
    ("OCEANSTOR-BACKUP", "Stockage de sauvegarde « OceanStor Backup »", "Serveurs et stockage", None, "Huawei",
     "OceanStor", 1, "Haute", "—", "À confirmer", None, "Modèle exact, usage, liste de contrôle à créer", SRC_PLAN,
     "A3", 18, 20, {}),
    ("DBSERVER1", "Serveur de base de données — nœud 1 de la grappe Oracle RAC", "Serveurs et stockage", None, "Huawei",
     "2288H V5", 1, "Critique", "Grappe Oracle RAC à deux nœuds", "Non", 350, None, SRC_AUDIT, "A3", 16, 17,
     {"alias": "dbserver1 ; DB Server_1", "version": "SLES 11 SP3 · Oracle 11gR2 RAC"}),
    ("DBSERVER2", "Serveur de base de données — nœud 2 de la grappe Oracle RAC", "Serveurs et stockage", None, "Huawei",
     "2288H V5", 1, "Critique", "Grappe Oracle RAC à deux nœuds", "Non", 350, None, SRC_AUDIT, "A3", 13, 14,
     {"alias": "dbserver2 ; DB Server_2", "version": "SLES 11 SP3 · Oracle 11gR2 RAC"}),
    ("OCEANSTOR-5500V5", "Baie de stockage OceanStor 5500", "Serveurs et stockage", None, "Huawei", "OceanStor 5500 V5", 1,
     "Haute", "—", "À confirmer", 1000, "Usage, liste de contrôle à créer", SRC_PLAN, "A3", 10, 12, {}),
    # --- Écart entre documents
    ("SERVEUR-07", "Septième serveur 2288H V5 cité par le rapport UPS", "Serveurs et stockage", None, "Huawei",
     "2288H V5", 1, "Moyenne", "—", "À confirmer", None,
     "Existence à confirmer : le rapport UPS compte 7 serveurs 2288H V5, le plan des baies en montre 6 dont un RH2288H",
     SRC_UPS, None, None, None, {"etat": "À confirmer"}),
]

# Codes renommés depuis le lot 1 (appliqués aux bases déjà initialisées)
RENOMMAGES = {"SAN-SNS2624": "SNS2624-01", "SERVEUR-06": "NETECO-SERVER", "FM800-CLIM": "FM800-AC1"}

EQUIPEMENTS = []
for (code, des, sysm, tc, fab, mod, q, crit, red, spof, pw, manq, src, bai, u1, u2, extra) in _E:
    EQUIPEMENTS.append({"code": code, "designation": des, "systeme": sysm, "type_controle": tc, "fabricant": fab,
                        "modele": mod, "quantite": q, "criticite": crit, "redondance": red, "point_unique": spof,
                        "puissance_w": pw, "a_completer": manq or None, "source": src, "salle": S, "baie": bai,
                        "u_debut": u1, "u_fin": u2, "etat": "En service", **extra})

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
