"""Moteur de base de données des tests du module Data Center.

Par défaut : SQLite en mémoire. Pour vérifier la compatibilité PostgreSQL (base de production Neon), pointer
DC_TEST_URL vers une base PostgreSQL JETABLE — ses tables « dc_ » sont supprimées avant chaque test :

    DC_TEST_URL=postgresql+psycopg2://utilisateur@localhost:5432/dc_test pytest -q tests/test_dc.py tests/test_dc_lot2.py
"""
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def moteur_dc():
    url = os.environ.get("DC_TEST_URL")
    if not url:
        eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    else:
        from dc import modele
        eng = create_engine(url)
        modele.meta.drop_all(eng)
    yield eng
    eng.dispose()
