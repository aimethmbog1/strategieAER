"""Tables du module Data Center (préfixe « dc_ »), créées automatiquement dans la base de l'application
(PostgreSQL Neon en production, SQLite en local)."""
from sqlalchemy import (Boolean, Column, DateTime, Float, ForeignKey, Integer, MetaData, String, Table, Text,
                        UniqueConstraint)

meta = MetaData()

SYSTEMES = ["Alimentation électrique", "Refroidissement", "Détection et extinction incendie", "Réseau",
            "Serveurs et stockage", "Sécurité physique", "Supervision", "Environnement"]
CRITICITES = ["Critique", "Haute", "Moyenne", "Basse"]
ETATS = ["En service", "Dégradé", "En panne", "En maintenance", "Hors service", "À confirmer"]
FREQUENCES = ["Journalier", "Hebdomadaire", "Mensuel", "Trimestriel", "Semestriel", "Annuel"]
STATUTS_CONTROLE = ["Conforme", "Non conforme", "S.O."]
SEVERITES = ["OK", "Information", "Avertissement", "Critique"]

salle = Table(
    "dc_salle", meta,
    Column("id", Integer, primary_key=True),
    Column("nom", String(120), nullable=False, unique=True),
    Column("description", Text),
)

baie = Table(
    "dc_baie", meta,
    Column("id", Integer, primary_key=True),
    Column("salle_id", Integer, ForeignKey("dc_salle.id")),
    Column("nom", String(80), nullable=False, unique=True),
    Column("position", String(40)),
    Column("puissance_max_kw", Float),
    Column("hauteur_u", Integer, default=42),
)

equipement = Table(
    "dc_equipement", meta,
    Column("id", Integer, primary_key=True),
    Column("code", String(60), nullable=False, unique=True),       # identifiant unique (ex. CORE_USG6620-01)
    Column("alias", String(200)),                                   # autres noms rencontrés, séparés par « ; »
    Column("designation", String(200), nullable=False),
    Column("systeme", String(60), nullable=False),
    Column("type_controle", String(40)),                            # rattachement aux listes de contrôle : RESEAU, SALLE…
    Column("salle_id", Integer, ForeignKey("dc_salle.id")),
    Column("baie_id", Integer, ForeignKey("dc_baie.id")),
    Column("u_debut", Integer),                                     # position dans la baie (unités U, du bas)
    Column("u_fin", Integer),
    Column("fabricant", String(80)),
    Column("modele", String(120)),
    Column("numero_serie", String(120)),
    Column("version", String(120)),
    Column("quantite", Integer, default=1),
    Column("criticite", String(20), default="Moyenne"),
    Column("etat", String(30), default="En service"),
    Column("redondance", String(120)),
    Column("point_unique", String(20), default="À confirmer"),     # point unique de défaillance : Oui / Non / À confirmer
    Column("date_mes", DateTime),                                   # mise en service
    Column("fin_garantie", DateTime),
    Column("fournisseur", String(120)),
    Column("puissance_w", Float),                                   # consommation estimée
    Column("a_completer", Text),                                    # informations manquantes
    Column("source", Text),
    Column("observations", Text),
)

modele_controle = Table(
    "dc_modele_controle", meta,
    Column("id", Integer, primary_key=True),
    Column("cible", String(60), nullable=False),                    # code d'équipement ou type de contrôle
    Column("phase", String(160)),
    Column("point", String(300), nullable=False),
    Column("commande", Text),
    Column("normal", Text),
    Column("a_signaler", Text),
    Column("frequence", String(20), nullable=False),
    Column("grandeur", String(40)),                                 # si mesure chiffrée : clé d'un seuil
    Column("source", String(160)),
    Column("actif", Boolean, default=True),
    UniqueConstraint("cible", "phase", "point", "commande", name="uq_dc_controle"),
)

seuil = Table(
    "dc_seuil", meta,
    Column("grandeur", String(40), primary_key=True),
    Column("libelle", String(160), nullable=False),
    Column("unite", String(20)),
    Column("avert_min", Float), Column("avert_max", Float),
    Column("crit_min", Float), Column("crit_max", Float),
    Column("reference", Text),
)

inspection = Table(
    "dc_inspection", meta,
    Column("id", Integer, primary_key=True),
    Column("date", DateTime, nullable=False),
    Column("equipement_id", Integer, ForeignKey("dc_equipement.id"), nullable=False),
    Column("frequence", String(20)),
    Column("inspecteur", String(120), nullable=False),
    Column("signature", String(64)),                                # empreinte SHA-256 (inspecteur + horodatage + relevés)
    Column("observations", Text),
    Column("auteur", String(80)),
)

releve = Table(
    "dc_releve", meta,
    Column("id", Integer, primary_key=True),
    Column("inspection_id", Integer, ForeignKey("dc_inspection.id"), nullable=False),
    Column("controle_id", Integer, ForeignKey("dc_modele_controle.id"), nullable=False),
    Column("statut", String(20)),
    Column("valeur", Float),
    Column("severite", String(20), nullable=False, default="OK"),
    Column("commentaire", Text),
    Column("photo_nom", String(200)),
    Column("photo_b64", Text),
)

reseau_ip = Table(      # donnée sensible : importée depuis la cartographie, jamais dans le code
    "dc_reseau_ip", meta,
    Column("id", Integer, primary_key=True),
    Column("plage", String(80)), Column("vlan", String(20)), Column("usage", Text),
    Column("passerelle", Text), Column("equipements", Text),
)

constat = Table(        # donnée sensible : constats de la cartographie, suivis comme actions correctives
    "dc_constat", meta,
    Column("id", Integer, primary_key=True),
    Column("numero", String(10)),
    Column("constat", Text, nullable=False),
    Column("equipements", Text),
    Column("nature", String(40)),
    Column("statut", String(30), default="Ouvert"),
    Column("action", Text),
    Column("responsable", String(120)),
    Column("echeance", DateTime),
    Column("source", String(160)),
)

audit = Table(
    "dc_audit", meta,
    Column("id", Integer, primary_key=True),
    Column("horodatage", DateTime, nullable=False),
    Column("utilisateur", String(80)),
    Column("role", String(20)),
    Column("action", String(80), nullable=False),
    Column("objet", String(80)),
    Column("objet_id", String(40)),
    Column("detail", Text),
)


# ============================================================================= lot 2
# Alertes, escalade, notifications, main courante, passation de consignes, annuaire.

STATUTS_ALERTE = ["Ouverte", "Acquittée", "Résolue"]
ORIGINES_ALERTE = ["Inspection", "Manuelle"]
SEVERITES_ALERTE = ["Information", "Avertissement", "Critique"]
# Niveaux d'escalade : chaque contact de l'annuaire est rattaché à un niveau (0 = ne reçoit pas d'alerte).
NIVEAUX = {1: "Niveau 1 — Technicien / astreinte", 2: "Niveau 2 — Responsable du Data Center",
           3: "Niveau 3 — Sous-directeur et Direction"}
TYPES_CONTACT = ["Interne AER", "Fournisseur", "Prestataire de maintenance", "Opérateur télécom", "Secours / urgence",
                 "Autre"]
CATEGORIES_EVENEMENT = ["Observation", "Incident", "Intervention", "Maintenance", "Visite / accès", "Consigne",
                        "Alerte", "Passation", "Rectificatif"]
POSTES = ["Journée", "Matin", "Après-midi", "Nuit", "Astreinte", "Week-end"]
CANAUX = ["Courriel", "Telegram"]

contact = Table(
    "dc_contact", meta,
    Column("id", Integer, primary_key=True),
    Column("nom", String(120), nullable=False),
    Column("fonction", String(160)),
    Column("organisation", String(160)),
    Column("type", String(40), default="Interne AER"),
    Column("systeme", String(60), default="Tous"),          # système couvert, ou « Tous »
    Column("niveau", Integer, default=0),                    # niveau d'escalade (0 : aucune alerte)
    Column("severite_min", String(20), default="Avertissement"),
    Column("courriel", String(160)),
    Column("telephone", String(60)),
    Column("telegram_id", String(40)),                       # identifiant de conversation Telegram (chat_id)
    Column("par_courriel", Boolean, default=True),
    Column("par_telegram", Boolean, default=False),
    Column("actif", Boolean, default=True),
    Column("observations", Text),
)

regle_escalade = Table(
    "dc_regle_escalade", meta,
    Column("id", Integer, primary_key=True),
    Column("severite", String(20), nullable=False),
    Column("delai_min", Integer, nullable=False),            # délai sans acquittement depuis l'émission
    Column("niveau", Integer, nullable=False),               # niveau de contacts notifié
    Column("actif", Boolean, default=True),
    UniqueConstraint("severite", "niveau", name="uq_dc_regle_escalade"),
)

alerte = Table(
    "dc_alerte", meta,
    Column("id", Integer, primary_key=True),
    Column("emise", DateTime, nullable=False),
    Column("severite", String(20), nullable=False),
    Column("systeme", String(60)),
    Column("equipement_id", Integer, ForeignKey("dc_equipement.id")),
    Column("controle_id", Integer, ForeignKey("dc_modele_controle.id")),   # alerte née d'un contrôle d'inspection
    Column("releve_id", Integer),
    Column("origine", String(20), nullable=False, default="Manuelle"),
    Column("titre", String(300), nullable=False),
    Column("description", Text),
    Column("statut", String(20), nullable=False, default="Ouverte"),
    Column("niveau_notifie", Integer, default=0),            # dernier niveau d'escalade notifié
    Column("acquittee", DateTime),
    Column("acquittee_par", String(120)),
    Column("commentaire_acquittement", Text),
    Column("resolue", DateTime),
    Column("resolue_par", String(120)),
    Column("resolution", Text),
    Column("auteur", String(80)),
)

notification = Table(
    "dc_notification", meta,
    Column("id", Integer, primary_key=True),
    Column("horodatage", DateTime, nullable=False),
    Column("alerte_id", Integer),
    Column("evenement_id", Integer),
    Column("niveau", Integer),
    Column("canal", String(20)),
    Column("destinataire", String(160)),
    Column("statut", String(30), nullable=False),            # Envoyée / Échec / Canal non configuré / Aucun destinataire
    Column("detail", Text),
)

evenement = Table(          # main courante : journal partagé, en ajout seul (jamais modifié ni supprimé)
    "dc_evenement", meta,
    Column("id", Integer, primary_key=True),
    Column("horodatage", DateTime, nullable=False),
    Column("categorie", String(30), nullable=False),
    Column("severite", String(20), default="Information"),
    Column("systeme", String(60)),
    Column("equipement_id", Integer, ForeignKey("dc_equipement.id")),
    Column("alerte_id", Integer),
    Column("rectifie_id", Integer),                          # entrée corrigée par ce rectificatif
    Column("description", Text, nullable=False),
    Column("auteur", String(80)),
    Column("auteur_nom", String(120)),
    Column("automatique", Boolean, default=False),
)

passation = Table(
    "dc_passation", meta,
    Column("id", Integer, primary_key=True),
    Column("horodatage", DateTime, nullable=False),
    Column("poste", String(30)),
    Column("sortant", String(120), nullable=False),
    Column("entrant", String(120)),
    Column("etat_general", String(20)),
    Column("situation", Text),                               # photographie automatique : alertes, écarts, retards
    Column("faits_marquants", Text),
    Column("travaux_en_cours", Text),
    Column("consignes", Text),
    Column("acceptee", DateTime),
    Column("acceptee_par", String(120)),
    Column("reserves", Text),
    Column("auteur", String(80)),
)


# Version du schéma et du référentiel : à incrémenter à chaque évolution, pour forcer la mise à jour de la base
# même si l'application n'a pas redémarré (le cache de Streamlit conserve sinon l'ancienne initialisation).
VERSION_SCHEMA = "2026-11-16.1"

# Colonnes ajoutées après la première version : créées par depot.initialiser() sur une base existante
COLONNES_AJOUTEES = {"dc_equipement": {"u_debut": "INTEGER", "u_fin": "INTEGER"}, "dc_baie": {"hauteur_u": "INTEGER"}}
