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
