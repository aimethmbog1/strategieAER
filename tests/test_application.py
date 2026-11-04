"""Tests de non-régression : chaque page s'exécute sans erreur, l'accès est protégé,
le moteur de paie reste conforme. Lancer :  pytest -q"""
import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

RACINE = Path(__file__).resolve().parent.parent
PAGES = ["Home.py"] + sorted(str(p.relative_to(RACINE)) for p in (RACINE / "pages").glob("*.py"))


@pytest.fixture(autouse=True)
def _cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(RACINE)


@pytest.mark.parametrize("page", PAGES)
def test_page_sans_erreur(page, monkeypatch):
    monkeypatch.setenv("AER_AUTH_DISABLED", "1")
    at = AppTest.from_file(str(RACINE / page), default_timeout=180).run()
    assert not at.exception, f"{page} : {[e.value for e in at.exception]}"


def test_acces_ferme_sans_comptes(monkeypatch):
    monkeypatch.delenv("AER_AUTH_DISABLED", raising=False)
    at = AppTest.from_file(str(RACINE / "Home.py"), default_timeout=120).run()
    assert any("configuration requise" in t.value for t in at.title)


def test_connexion(monkeypatch):
    monkeypatch.delenv("AER_AUTH_DISABLED", raising=False)
    from utils.auth import hacher_mot_de_passe
    at = AppTest.from_file(str(RACINE / "Home.py"), default_timeout=120)
    at.secrets["auth"] = {"users": {"test": {"nom": "Test", "role": "lecteur",
                                             "password_hash": hacher_mot_de_passe("motdepasse-test-123")}}}
    at.run()
    at.text_input[0].input("test"); at.text_input[1].input("mauvais")
    at.button[0].click().run()
    assert any("incorrect" in e.value for e in at.error)
    at.text_input[1].input("motdepasse-test-123"); at.button[0].click().run()
    assert not at.exception and at.session_state["auth_user"]["role"] == "lecteur"


def test_paie_interdite_au_lecteur(monkeypatch):
    monkeypatch.delenv("AER_AUTH_DISABLED", raising=False)
    page = next(p for p in PAGES if "Masse_salariale" in p)
    at = AppTest.from_file(str(RACINE / page), default_timeout=120)
    at.session_state["auth_user"] = {"login": "l", "nom": "L", "role": "lecteur"}
    at.secrets["auth"] = {"users": {"l": {"role": "lecteur", "password_hash": "x"}}}
    at.run()
    assert any("ne donne pas accès" in w.value for w in at.warning)


def test_moteur_paie_reference():
    import sys
    sys.path.insert(0, str(RACINE))
    from utils.paie_moteur import Agent, calculer_paie, charger_parametres
    P = charger_parametres(str(RACINE / "data" / "parametres_paie_aer.json"))
    r = calculer_paie(Agent(categorie=10, echelon="C", poste="P2", enfants=2), P)
    assert round(r["brut_total"]) == 969047 and round(r["net_a_payer"]) == 763018
    e = calculer_paie(Agent(categorie=10, echelon="A", en_essai="Oui"), P)
    assert e["brut_total"] == P["GRILLE"]["10"][0]
