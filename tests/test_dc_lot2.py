"""Tests du lot 2 du module Data Center : escalade, alertes et acquittement, notifications, main courante,
passation de consignes, annuaire."""
from datetime import datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from dc import depot, exploitation as ex, modele, notifications
from dc.regles import (PALIERS_DEFAUT, Palier, delai_moyen_min, destinataire_concerne, format_duree, paliers_dus,
                       prochain_palier, severite_alerte_fusion)

E0 = datetime(2026, 11, 16, 10, 0)


# ----------------------------------------------------------------------------- règles pures
def test_paliers_critique():
    niveaux = lambda mn, deja=0: [p.niveau for p in paliers_dus("Critique", E0, None, None, E0 + timedelta(minutes=mn), deja)]
    assert niveaux(0) == [1]                 # niveau 1 notifié dès l'émission
    assert niveaux(14, 1) == []
    assert niveaux(15, 1) == [2]             # 15 min sans acquittement
    assert niveaux(30, 2) == [3]             # 30 min sans acquittement
    assert niveaux(45) == [1, 2, 3]          # rattrapage si personne n'a ouvert l'application
    assert niveaux(600, 3) == []


def test_paliers_avertissement_et_information():
    n = lambda sev, mn, deja=0: [p.niveau for p in paliers_dus(sev, E0, None, None, E0 + timedelta(minutes=mn), deja)]
    assert n("Avertissement", 0) == [1]
    assert n("Avertissement", 239, 1) == [] and n("Avertissement", 240, 1) == [2]   # 4 h
    assert n("Avertissement", 10_000, 2) == []                                       # pas de niveau 3
    assert n("Information", 10_000) == []                                            # jamais escaladée


def test_acquittement_ou_resolution_arrete_l_escalade():
    tard = E0 + timedelta(hours=5)
    assert paliers_dus("Critique", E0, E0 + timedelta(minutes=5), None, tard) == []
    assert paliers_dus("Critique", E0, None, E0 + timedelta(minutes=5), tard) == []


def test_prochain_palier():
    p, quand = prochain_palier("Critique", E0, 1)
    assert p.niveau == 2 and quand == E0 + timedelta(minutes=15)
    assert prochain_palier("Critique", E0, 3) is None and prochain_palier("Information", E0) is None


def test_destinataire_concerne():
    ok = lambda **k: destinataire_concerne(**({"niveau_contact": 2, "severite_min": "Avertissement", "systeme_contact": "Tous",
                                               "actif": True, "niveau": 2, "severite": "Critique", "systeme": "Réseau"} | k))
    assert ok()
    assert not ok(actif=False) and not ok(niveau_contact=1) and not ok(niveau_contact=0)
    assert not ok(severite_min="Critique", severite="Avertissement")
    assert ok(systeme_contact="Réseau") and not ok(systeme_contact="Refroidissement")
    assert ok(systeme_contact=None) and ok(systeme_contact="Refroidissement", systeme=None)


def test_fusion_delais_et_format():
    assert severite_alerte_fusion("Avertissement", "Critique") == "Critique"
    assert severite_alerte_fusion("Critique", "Avertissement") == "Critique"
    assert delai_moyen_min([E0, E0, None], [E0 + timedelta(minutes=10), E0 + timedelta(minutes=20), E0]) == 15.0
    assert delai_moyen_min([], []) is None
    assert [format_duree(x) for x in (None, 12, 185, 3000)] == ["—", "12 min", "3 h 05", "2 j 2 h"]


def test_paliers_par_defaut_conformes_a_la_validation():
    assert {(p.severite, p.delai_min, p.niveau) for p in PALIERS_DEFAUT} == {
        ("Critique", 0, 1), ("Critique", 15, 2), ("Critique", 30, 3), ("Avertissement", 0, 1), ("Avertissement", 240, 2)}


# ----------------------------------------------------------------------------- base de test
class Boite:
    """Faux transport : enregistre les messages au lieu de les envoyer."""
    def __init__(self, statut="Envoyée"):
        self.messages, self.statut = [], statut

    def __call__(self, canal, adresse, sujet, corps):
        self.messages.append({"canal": canal, "adresse": adresse, "sujet": sujet, "corps": corps})
        return notifications.Resultat(self.statut)


@pytest.fixture()
def base(monkeypatch, moteur_dc):
    eng = moteur_dc
    monkeypatch.setattr(depot, "MOTEUR", eng)
    boite = Boite()
    monkeypatch.setattr(notifications, "envoyer", boite)      # aucun envoi réel pendant les tests
    depot._INIT_FAIT.clear()
    depot.initialiser()
    return boite


def _annuaire():
    vide = ex.contacts()
    df = pd.DataFrame([
        {"nom": "Technicien A", "niveau": 1, "courriel": "tech@exemple.cm", "par_courriel": True},
        {"nom": "Responsable B", "niveau": 2, "courriel": "resp@exemple.cm", "par_courriel": True,
         "telegram_id": "111", "par_telegram": True},
        {"nom": "Direction C", "niveau": 3, "courriel": "dir@exemple.cm", "par_courriel": True, "severite_min": "Critique"},
        {"nom": "Fournisseur D", "niveau": 0, "type": "Fournisseur", "telephone": "600000000"},
    ])
    return ex.enregistrer_contacts(vide, df)


def _fm800():
    eq = depot.equipements()
    fm = eq[eq["code"] == "FM800"].iloc[0]
    ctl = depot.controles_pour(fm)
    return int(fm["id"]), int(ctl[ctl["grandeur"] == "temp_c"]["id"].iloc[0]), int(ctl[ctl["grandeur"].isna()]["id"].iloc[0])


def _vieillir(alerte_id, minutes):
    from sqlalchemy import update
    with depot.moteur().begin() as cx:
        cx.execute(update(modele.alerte).where(modele.alerte.c.id == alerte_id)
                   .values(emise=depot.maintenant() - timedelta(minutes=minutes)))


# ----------------------------------------------------------------------------- annuaire et règles en base
def test_regles_initiales_et_modification(base):
    assert {(p.severite, p.delai_min, p.niveau) for p in ex.paliers()} == {(p.severite, p.delai_min, p.niveau) for p in PALIERS_DEFAUT}
    d = ex.regles_df()
    d.loc[(d["severite"] == "Critique") & (d["niveau"] == 2), "delai_min"] = 10
    ex.modifier_regles(d)
    assert Palier("Critique", 10, 2) in ex.paliers()
    d.loc[(d["severite"] == "Critique") & (d["niveau"] == 3), "delai_min"] = 5      # délai décroissant : refusé
    with pytest.raises(ValueError):
        ex.modifier_regles(d)


def test_annuaire(base):
    assert _annuaire() == {"créés": 4, "modifiés": 0, "supprimés": 0}
    c = ex.contacts()
    assert len(c) == 4 and c.set_index("nom").at["Fournisseur D", "systeme"] == "Tous"
    ap = c.copy()
    ap.loc[ap["nom"] == "Technicien A", "telephone"] = "677000000"
    ap = ap[ap["nom"] != "Fournisseur D"]
    assert ex.enregistrer_contacts(c, ap) == {"créés": 0, "modifiés": 1, "supprimés": 1}
    assert list(ex.destinataires(2, "Critique", "Réseau")["nom"]) == ["Responsable B"]
    assert ex.destinataires(3, "Avertissement", None).empty          # la direction ne veut que le critique


def test_annuaire_controles(base):
    mauvais = pd.DataFrame([{"nom": "", "niveau": 0}, {"nom": "X", "niveau": 1, "courriel": "pas-une-adresse", "par_courriel": True},
                            {"nom": "Y", "niveau": 2, "par_courriel": True}])
    err = ex.controler_contacts(mauvais)
    assert len(err) == 3 and any("sans canal" in e for e in err) and any("invalide" in e for e in err)
    with pytest.raises(ValueError):
        ex.enregistrer_contacts(ex.contacts(), mauvais)
    assert ex.contacts().empty


# ----------------------------------------------------------------------------- alertes
def test_inspection_cree_alertes_et_notifie_le_niveau_1(base):
    _annuaire()
    eq, temp, autre = _fm800()
    _, bilan = depot.enregistrer_inspection(eq, "Inspecteur", "Hebdomadaire",
                                            [{"controle_id": temp, "statut": "Conforme", "valeur": 33.0},
                                             {"controle_id": autre, "statut": "Non conforme"}])
    assert bilan["alertes"] == {"créées": 2, "aggravées": 0, "résolues": 0} and "alertes_erreur" not in bilan
    al = ex.alertes()
    assert len(al) == 2 and set(al["severite"]) == {"Critique"} and set(al["origine"]) == {"Inspection"}
    assert set(al["niveau_notifie"]) == {1}
    assert len(base.messages) == 2 and {x["adresse"] for x in base.messages} == {"tech@exemple.cm"}
    assert "CRITIQUE" in base.messages[0]["sujet"] and "Acquitter" in base.messages[0]["corps"]
    assert ex.synchroniser_alertes() == {"créées": 0, "aggravées": 0, "résolues": 0}      # idempotent
    assert (ex.evenements()["categorie"] == "Alerte").sum() == 2                           # consignées en main courante


def test_escalade_puis_acquittement(base):
    _annuaire()
    aid = ex.signaler("Critique", "Arrêt de la climatisation AC1", "Température en hausse", systeme="Refroidissement")
    assert ex.traiter_escalades()[0]["niveau"] == 1 and len(base.messages) == 1
    assert ex.traiter_escalades() == []                                   # rien avant 15 min
    _vieillir(aid, 16)
    f = ex.traiter_escalades()
    assert [x["niveau"] for x in f] == [2] and len(base.messages) == 3    # responsable : courriel + Telegram
    assert {x["canal"] for x in base.messages[1:]} == {"Courriel", "Telegram"}
    assert "ESCALADE" in base.messages[1]["corps"]
    ex.acquitter(aid, "Responsable B", "Je me déplace")
    _vieillir(aid, 120)
    assert ex.traiter_escalades() == [] and len(base.messages) == 3       # acquittée : plus d'escalade
    a = ex.alertes().iloc[0]
    assert a["statut"] == "Acquittée" and a["niveau_notifie"] == 2
    with pytest.raises(ValueError):
        ex.acquitter(aid, "Autre")                                       # déjà acquittée
    ex.resoudre(aid, "Responsable B", "Disjoncteur réarmé")
    assert ex.alertes().iloc[0]["statut"] == "Résolue" and ex.alertes_en_cours().empty
    with pytest.raises(ValueError):
        ex.resoudre(aid, "Autre", "x")


def test_escalade_jusqu_au_niveau_3_sans_doublon(base):
    _annuaire()
    aid = ex.signaler("Critique", "Coupure secteur, onduleur sur batteries")
    _vieillir(aid, 40)
    assert [x["niveau"] for x in ex.traiter_escalades()] == [1, 2, 3]
    assert len(base.messages) == 4 and ex.traiter_escalades() == []       # second passage : aucun renvoi
    n = ex.notifications_df()
    assert len(n) == 4 and set(n["statut"]) == {"Envoyée"}


def test_avertissement_n_atteint_pas_la_direction(base):
    _annuaire()
    aid = ex.signaler("Avertissement", "Filtre de climatisation encrassé")
    _vieillir(aid, 10_000)
    assert [x["niveau"] for x in ex.traiter_escalades()] == [1, 2]
    assert "dir@exemple.cm" not in {x["adresse"] for x in base.messages}


def test_annuaire_vide_ou_canal_absent_laisse_une_trace(base, monkeypatch):
    ex.signaler("Critique", "Alerte sans destinataire")
    ex.traiter_escalades()
    assert list(ex.notifications_df()["statut"]) == ["Aucun destinataire"]
    monkeypatch.setattr(notifications, "envoyer", Boite("Canal non configuré"))
    _annuaire()
    ex.signaler("Critique", "Alerte sans serveur d'envoi")
    ex.traiter_escalades()
    assert "Canal non configuré" in set(ex.notifications_df()["statut"])
    assert set(ex.alertes()["niveau_notifie"]) == {1}                     # l'alerte reste visible dans l'application


def test_aggravation_reemet_et_retour_conforme_resout(base):
    _annuaire()
    eq, temp, _ = _fm800()
    t0 = depot.maintenant()
    depot.enregistrer_inspection(eq, "I", None, [{"controle_id": temp, "statut": "Conforme", "valeur": 28.0}], date=t0)
    a = ex.alertes().iloc[0]
    assert a["severite"] == "Avertissement"
    ex.acquitter(int(a["id"]), "Technicien A")
    _, b = depot.enregistrer_inspection(eq, "I", None, [{"controle_id": temp, "statut": "Conforme", "valeur": 34.0}],
                                        date=t0 + timedelta(minutes=1))
    assert b["alertes"]["aggravées"] == 1
    a = ex.alertes().iloc[0]
    assert len(ex.alertes()) == 1 and a["severite"] == "Critique" and a["statut"] == "Ouverte" and pd.isna(a["acquittee"])
    _, b = depot.enregistrer_inspection(eq, "I", None, [{"controle_id": temp, "statut": "Conforme", "valeur": 22.0}],
                                        date=t0 + timedelta(minutes=2))
    assert b["alertes"]["résolues"] == 1
    a = ex.alertes().iloc[0]
    assert a["statut"] == "Résolue" and a["resolue_par"] == ex.SYSTEME_AUTO and "redevenu conforme" in a["resolution"]


def test_alerte_resolue_a_la_main_non_recreee(base):
    eq, temp, _ = _fm800()
    depot.enregistrer_inspection(eq, "I", None, [{"controle_id": temp, "statut": "Conforme", "valeur": 33.0}])
    ex.resoudre(int(ex.alertes().iloc[0]["id"]), "Technicien A", "Climatisation relancée")
    assert ex.synchroniser_alertes()["créées"] == 0 and len(ex.alertes()) == 1


def test_validations_alertes(base):
    for args in (("Grave", "x"), ("Critique", "  ")):
        with pytest.raises(ValueError):
            ex.signaler(*args)
    aid = ex.signaler("Information", "Visite du prestataire prévue")
    assert ex.traiter_escalades() == []                                   # une information n'est pas notifiée
    with pytest.raises(ValueError):
        ex.acquitter(aid, "")
    with pytest.raises(ValueError):
        ex.resoudre(aid, "Nom", "")
    long = ex.signaler("Avertissement", "T" * 500)                       # titre tronqué (compatibilité PostgreSQL)
    assert len(ex.alertes().set_index("id").at[long, "titre"]) == 300


def test_indicateurs_alertes(base):
    a1 = ex.signaler("Critique", "A")
    ex.signaler("Avertissement", "B")
    _vieillir(a1, 30)
    ex.acquitter(a1, "T")
    ind = ex.indicateurs_alertes(ex.alertes(), depot.maintenant() - timedelta(days=30))
    assert ind["en_cours"] == 2 and ind["non_acquittees"] == 1 and ind["critiques"] == 1 and ind["emises"] == 2
    assert 29 <= ind["delai_acquittement"] <= 31 and ind["delai_resolution"] is None


# ----------------------------------------------------------------------------- main courante et passation
def test_main_courante_ajout_seul_et_diffusion(base):
    _annuaire()
    e1 = ex.ajouter_evenement("Intervention", "Remplacement d'un ventilateur", "Avertissement", "Refroidissement")
    e2 = ex.ajouter_evenement("Rectificatif", "Il s'agissait du ventilateur n° 2", rectifie_id=e1)
    ev = ex.evenements().set_index("id")
    assert ev.at[e2, "rectifie_id"] == e1 and not bool(ev.at[e1, "automatique"])
    assert not hasattr(ex, "modifier_evenement") and not hasattr(ex, "supprimer_evenement")
    with pytest.raises(ValueError):
        ex.ajouter_evenement("Intervention", " ")
    with pytest.raises(ValueError):
        ex.ajouter_evenement("Intervention", "x", quand=depot.maintenant() + timedelta(days=1))
    r = ex.diffuser_evenement(e1, [2, 3])
    assert r["destinataires"] == 2 and r["envoyées"] == 3 and "ventilateur" in base.messages[0]["corps"]


def test_passation(base):
    ex.signaler("Critique", "Fuite d'eau détectée")
    with pytest.raises(ValueError):
        ex.enregistrer_passation("Nuit", "Agent sortant", "", "", "", "")
    pid = ex.enregistrer_passation("Nuit", "Agent sortant", "Agent entrant", "RAS", "", "Surveiller la fuite")
    p = ex.passations().iloc[0]
    assert p["etat_general"] == "Critique" and "Alertes en cours : 1" in p["situation"] and "Fuite d'eau" in p["situation"]
    assert pd.isna(p["acceptee"])
    ex.accepter_passation(pid, "Agent entrant", "Clé de la salle non remise")
    assert ex.passations().iloc[0]["acceptee_par"] == "Agent entrant"
    with pytest.raises(ValueError):
        ex.accepter_passation(pid, "Autre")
    assert (ex.evenements()["categorie"] == "Passation").sum() == 2


def test_tracabilite(base):
    _annuaire()
    aid = ex.signaler("Critique", "Test")
    ex.acquitter(aid, "T")
    ex.resoudre(aid, "T", "ok")
    actions = set(depot.journal_audit()["action"])
    assert {"création", "émission", "acquittement", "résolution"} <= actions


# ----------------------------------------------------------------------------- notifications (sans réseau)
def test_canaux_non_configures(monkeypatch):
    for v in ("DC_SMTP_HOST", "DC_TELEGRAM_TOKEN"):
        monkeypatch.delenv(v, raising=False)
    assert notifications.envoyer_courriel("a@b.cm", "s", "c").statut == "Canal non configuré"
    assert notifications.envoyer_telegram("1", "t").statut == "Canal non configuré"
    assert notifications.envoyer_courriel.__module__ == "dc.notifications"


def test_message_sans_donnee_sensible():
    import re
    s, c = notifications.message_alerte({"id": 7, "severite": "Critique", "titre": "FM800 — Température", "systeme": "Environnement",
                                         "emise": E0, "description": "33 °C"}, 2, modele.NIVEAUX[2], 16, "FM800")
    assert s.startswith("[Data Center AER] CRITIQUE") and "16 min" in c and "FM800" in c
    assert not re.search(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", s + c)


def test_echec_telegram_ne_divulgue_pas_le_jeton(monkeypatch):
    monkeypatch.setenv("DC_TELEGRAM_TOKEN", "123456:JETON-SECRET")
    import requests
    def boom(*a, **k):
        raise requests.ConnectionError("https://api.telegram.org/bot123456:JETON-SECRET/sendMessage")
    monkeypatch.setattr(requests, "post", boom)
    r = notifications.envoyer_telegram("1", "t")
    assert r.statut == "Échec" and "JETON-SECRET" not in r.detail


def test_longueurs_lot2(base):
    from sqlalchemy import String
    for libelle in list(modele.NIVEAUX.values()) + modele.TYPES_CONTACT + modele.CATEGORIES_EVENEMENT + modele.POSTES:
        assert len(libelle) <= 40
    assert all(len(x) <= modele.evenement.c.categorie.type.length for x in modele.CATEGORIES_EVENEMENT)
    assert all(len(x) <= modele.contact.c.type.type.length for x in modele.TYPES_CONTACT)
    assert isinstance(modele.alerte.c.titre.type, String) and modele.alerte.c.titre.type.length == 300


def test_etat_systeme_tient_compte_des_alertes_manuelles(base):
    from dc import analyse
    ex.signaler("Critique", "Coupure secteur", systeme="Alimentation électrique")
    eq = depot.equipements()
    vide = analyse.ecarts_ouverts(depot.releves())
    sans = analyse.etat_systemes(eq, vide, modele.SYSTEMES).set_index("Système")
    avec = analyse.etat_systemes(eq, vide, modele.SYSTEMES, ex.alertes_en_cours()).set_index("Système")
    assert sans.at["Alimentation électrique", "État"] == "OK"
    assert avec.at["Alimentation électrique", "État"] == "Critique" and avec.at["Alimentation électrique", "Alertes en cours"] == 1
    assert avec.at["Réseau", "État"] == "OK"
