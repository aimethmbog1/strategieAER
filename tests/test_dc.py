"""Tests de la logique métier du module Data Center : seuils, écarts, échéances, escalade, indicateurs, base."""
import io
from datetime import datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from dc import analyse, depot, imports, modele, referentiel
from dc.regles import (Seuil, autonomie_estimee_min, est_en_retard, evaluer_mesure, evaluer_releve, niveau_escalade,
                       taux_conformite, taux_respect_plan)

T = Seuil("temp_c", "Température", "°C", avert_min=18, avert_max=27, crit_max=32)
H = Seuil("hr_pct", "Humidité", "%", avert_min=20, avert_max=60, crit_max=80)


@pytest.mark.parametrize("v,att", [(22, "OK"), (18, "OK"), (27, "OK"), (27.5, "Avertissement"), (16, "Avertissement"),
                                   (32, "Avertissement"), (32.1, "Critique"), (None, "OK")])
def test_seuil_temperature(v, att):
    assert evaluer_mesure(v, T) == att


def test_seuil_humidite():
    assert [evaluer_mesure(v, H) for v in (45, 15, 65, 85)] == ["OK", "Avertissement", "Avertissement", "Critique"]


def test_releve_non_conforme_selon_criticite():
    assert evaluer_releve("Conforme", None, None) == "OK"
    assert evaluer_releve("S.O.", None, None) == "OK"
    assert evaluer_releve("Non conforme", None, None, "Moyenne") == "Avertissement"
    assert evaluer_releve("Non conforme", None, None, "Critique") == "Critique"
    assert evaluer_releve("Conforme", 35, T) == "Critique"  # la mesure prime sur la case cochée


def test_echeances():
    m = datetime(2026, 11, 11, 10)
    assert est_en_retard(None, "Mensuel", m)
    assert est_en_retard(datetime(2026, 11, 10, 18), "Journalier", m)
    assert not est_en_retard(datetime(2026, 11, 11, 7), "Journalier", m)
    assert not est_en_retard(m - timedelta(days=6), "Hebdomadaire", m)
    assert est_en_retard(m - timedelta(days=8), "Hebdomadaire", m)


def test_escalade():
    e = datetime(2026, 11, 11, 10, 0)
    assert niveau_escalade("Critique", e, None, e + timedelta(minutes=10)) == []
    assert len(niveau_escalade("Critique", e, None, e + timedelta(minutes=16))) == 1
    assert len(niveau_escalade("Critique", e, None, e + timedelta(minutes=31))) == 2
    assert niveau_escalade("Critique", e, e + timedelta(minutes=5), e + timedelta(hours=2)) == []
    assert niveau_escalade("Avertissement", e, None, e + timedelta(hours=3)) == []
    assert len(niveau_escalade("Avertissement", e, None, e + timedelta(hours=4))) == 1
    assert niveau_escalade("Information", e, None, e + timedelta(days=2)) == []


def test_indicateurs_simples():
    assert taux_conformite(["OK", "OK", "Critique", "Avertissement"]) == 50.0
    assert taux_respect_plan(10, 3) == 70.0 and taux_respect_plan(0, 0) is None
    assert autonomie_estimee_min(8640, 4800) == 89  # cohérent avec le test UPS du 13/07/2026 (90 min)


def test_referentiel():
    codes = [e["code"] for e in referentiel.EQUIPEMENTS]
    assert len(codes) == len(set(codes))
    assert {"FM800-UPS", "CORE_USG6620-01", "DBSERVER1", "OCEANPROTECT-X3000"} <= set(codes)
    ctl = referentiel.controles()
    assert len(ctl) >= 110 and {c["frequence"] for c in ctl} <= set(modele.FREQUENCES)
    assert {"disque_pct", "sauvegarde_h", "horloge_s", "temp_c", "hr_pct"} <= {c["grandeur"] for c in ctl}
    # aucune adresse IP dans le contenu embarqué
    import re
    assert not re.search(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", str(referentiel.EQUIPEMENTS) + str(ctl).replace("127.0.0.1", ""))


@pytest.fixture()
def base(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr(depot, "MOTEUR", eng)
    depot._INIT_FAIT.clear()
    depot.initialiser()
    return eng


def test_initialisation_idempotente(base):
    n = len(depot.equipements())
    depot._INIT_FAIT.clear()
    assert depot.initialiser() == {} and len(depot.equipements()) == n
    assert len(depot.controles()) >= 110 and "temp_c" in depot.seuils()


def test_inspection_ecarts_et_plan(base):
    eq = depot.equipements()
    fm = eq[eq["code"] == "FM800"].iloc[0]
    ctl = depot.controles_pour(fm)
    assert len(ctl) == 12  # liste « environnement de la salle »
    temp = int(ctl[ctl["grandeur"] == "temp_c"]["id"].iloc[0])
    autre = int(ctl[ctl["grandeur"].isna()]["id"].iloc[0])
    _, bilan = depot.enregistrer_inspection(int(fm["id"]), "Inspecteur test", "Hebdomadaire",
                                            [{"controle_id": temp, "statut": "Conforme", "valeur": 33.0},
                                             {"controle_id": autre, "statut": "Non conforme"}])
    assert bilan["Critique"] == 2  # 33 °C > 32 °C ; non-conformité sur équipement critique
    ec = analyse.ecarts_ouverts(depot.releves())
    assert len(ec) == 2
    depot.enregistrer_inspection(int(fm["id"]), "Inspecteur test", "Hebdomadaire",
                                 [{"controle_id": temp, "statut": "Conforme", "valeur": 23.0}],
                                 date=depot.maintenant() + timedelta(minutes=1))
    assert len(analyse.ecarts_ouverts(depot.releves())) == 1  # l'écart de température est refermé
    plan = analyse.plan_controles(eq, depot.controles(), depot.releves(), depot.maintenant())
    assert not plan[(plan["equipement_id"] == fm["id"]) & (plan["controle_id"] == temp)]["en_retard"].iloc[0]
    assert len(depot.journal_audit()) >= 3


def test_modification_registre_tracee(base):
    av = depot.equipements()
    ap = av.copy()
    ap.loc[ap["code"] == "FM800-UPS", "a_completer"] = "Configuration de redondance"
    assert depot.modifier_equipements(av, ap) == 1
    assert depot.journal_audit()["action"].iloc[0] == "modification"


def test_import_cartographie(base):
    from docx import Document
    d = Document()
    t = d.add_table(rows=2, cols=5)
    for c, v in zip(t.rows[0].cells, ["Plage / Sous-reseau", "VLAN", "Usage", "Passerelle", "Equipements"]):
        c.text = v
    for c, v in zip(t.rows[1].cells, ["10.0.0.0/29", "1000", "Management", "10.0.0.1", "LSW"]):
        c.text = v
    t2 = d.add_table(rows=2, cols=4)
    for c, v in zip(t2.rows[0].cells, ["N°", "Constat", "Equipement(s)", "Nature"]):
        c.text = v
    for c, v in zip(t2.rows[1].cells, ["1", "Telnet autorisé", "LSW", "Securite"]):
        c.text = v
    buf = io.BytesIO()
    d.save(buf)
    ip, cst = imports.lire_cartographie(buf.getvalue())
    assert len(ip) == 1 and len(cst) == 1
    assert depot.remplacer_donnees_sensibles(ip, cst, "test")["constats_ajoutes"] == 1
    assert depot.remplacer_donnees_sensibles(ip, cst, "test")["constats_ajoutes"] == 0


def test_plan_des_baies():
    eqs = pd.DataFrame(referentiel.EQUIPEMENTS)
    occ, conflits = analyse.occupation_baies(eqs)
    assert conflits == []
    assert set(occ["Baie"]) == {"A1", "A2", "A3"}
    a2 = eqs[eqs["baie"] == "A2"]
    assert {"FM800-UPS", "FM800-ECC800", "FM800-AC1", "FM800-AC2", "FM800-PDU"} <= set(a2["code"])


def test_renommage_et_completion(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr(depot, "MOTEUR", eng)
    depot._INIT_FAIT.clear()
    modele.meta.create_all(eng)
    from sqlalchemy import insert
    with eng.begin() as cx:  # base « lot 1 » : ancien code, sans emplacement, avec une saisie utilisateur
        cx.execute(insert(modele.equipement).values(code="SAN-SNS2624", designation="x", systeme="Réseau",
                                                    fournisseur="Fournisseur saisi"))
    depot.initialiser()
    e = depot.equipements().set_index("code")
    assert "SAN-SNS2624" not in e.index and e.at["SNS2624-01", "baie"] == "A3"
    assert e.at["SNS2624-01", "fournisseur"] == "Fournisseur saisi"  # jamais écrasé
    assert e.at["SNS2624-01", "u_debut"] == 26


def test_longueurs_compatibles_postgresql():
    """PostgreSQL refuse un texte plus long que sa colonne (SQLite l'accepte) : on vérifie tout le référentiel."""
    from sqlalchemy import String
    tables = ((modele.salle, referentiel.SALLES), (modele.baie, referentiel.BAIES),
              (modele.equipement, referentiel.EQUIPEMENTS), (modele.modele_controle, referentiel.controles()),
              (modele.seuil, [s.__dict__ for s in referentiel.SEUILS]))
    trop_longs = [(t.name, c.name, r.get(c.name)) for t, lignes in tables for r in lignes for c in t.columns
                  if isinstance(c.type, String) and c.type.length and isinstance(r.get(c.name), str)
                  and len(r[c.name]) > c.type.length]
    assert trop_longs == []
