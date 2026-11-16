"""Parcours de la page « Suivi de la maintenance » dans une base SQLite jetable : saisie de l'état d'une
centrale, création d'une fiche (bon d'intervention enrichi), mise à jour d'une fiche de l'application et
d'une fiche de journal. Les refus de saisie sont vérifiés au passage."""
import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from utils import gmao as g

RACINE = Path(__file__).resolve().parents[1]
PAGE = str(next((RACINE / "vues").glob("26_*")))


@pytest.fixture()
def app(monkeypatch, tmp_path):
    monkeypatch.chdir(RACINE)
    monkeypatch.setenv("AER_AUTH_DISABLED", "1")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'essai.sqlite'}")
    import utils.storage as stg
    for nom in ("_eng", "_moteur"):                     # moteur mis en cache : on repart d'une base vide
        f = getattr(stg, nom, None)
        if f is not None and hasattr(f, "clear"):
            f.clear()
    at = AppTest.from_file(PAGE, default_timeout=300).run()
    assert not at.exception, at.exception[0].stack_trace[-5:]
    yield at
    for nom in ("_eng", "_moteur"):                     # les tests suivants ne doivent pas hériter de cette base
        f = getattr(stg, nom, None)
        if f is not None and hasattr(f, "clear"):
            f.clear()


def _valider(at, mot):
    [b for b in at.get("form_submit_button") if mot in b.label][0].click()
    at.run()
    assert not at.exception, at.exception[0].stack_trace[-5:]
    return [x.value for x in at.success], [x.value for x in at.error]


def _cle(libelle):
    return g.cle(libelle.split(" (Phase")[0])


def test_parcours_etat_fiche_backlog(app):
    at = app
    # --- état d'une centrale : refusé sans cause, puis enregistré
    k = _cle(at.selectbox(key="smp_site").options[0])
    at.selectbox(key="smp_site").set_value(k).run()
    at.selectbox(key=f"smp_e_{k}_0").set_value("À l'arrêt")
    ok, err = _valider(at, "Enregistrer l'état")
    assert not ok and "cause" in err[0]
    at.selectbox(key=f"smp_e_{k}_0").set_value("À l'arrêt")
    at.selectbox(key=f"smp_c_{k}_0").set_value("Vandalisme")
    ok, err = _valider(at, "Enregistrer l'état")
    assert ok and not err
    es = at.session_state["gmao_etats_saisis"]
    assert len(es) == 1 and es["etat"].iloc[0] == "À l'arrêt" and es["cle_site"].iloc[0] == k

    # --- nouvelle fiche : refusée vide, puis créée (CRITIQUE → échéance à 7 jours)
    ok, err = _valider(at, "Enregistrer la fiche")
    assert not ok and "matériel" in err[0] and "site" in err[0]
    at.selectbox(key="smf_site_0").set_value(_cle(at.selectbox(key="smf_site_0").options[3]))
    at.selectbox(key="smf_prio_0").set_value("CRITIQUE").run()
    at.selectbox(key="smf_cat_0").set_value(at.selectbox(key="smf_cat_0").options[1])
    at.selectbox(key="smf_mat_0").set_value("Batterie")
    at.number_input(key="smf_qa_0").set_value(4)
    at.selectbox(key="smf_arr_0").set_value("À l'arrêt")
    at.text_area(key="smf_desc_0").set_value("Batteries déchargées (essai)")
    ok, err = _valider(at, "Enregistrer la fiche")
    assert ok and not err
    bi = at.session_state["gmao_bi"].iloc[-1]
    assert (bi["type"], bi["priorite"], bi["equipement"], bi["qte_affectee"]) == ("Corrective", "Critique", "Batterie", 4)
    assert bool(bi["centrale_arret"]) and (bi["date_prevue"] - bi["date_creation"]).days == 7

    # --- backlog : mise à jour de cette fiche, refusée (quantité) puis clôturée
    at.text_input(key="smb_q").set_value("essai").run()
    at.selectbox(key="smb_sel").set_value(0).run()
    at.selectbox(key="smb_st_0").set_value("Clôturé")
    at.number_input(key="smb_qr_0").set_value(9)
    ok, err = _valider(at, "Mettre à jour")
    assert not ok and "dépasse" in err[0]
    at.selectbox(key="smb_st_0").set_value("Clôturé")
    at.number_input(key="smb_qr_0").set_value(4)
    ok, err = _valider(at, "Mettre à jour")
    assert ok and not err
    bi = at.session_state["gmao_bi"].iloc[-1]
    assert bi["statut"] == "Clôturé" and bi["qte_remplacee"] == 4 and bi["date_fin"] == bi["date_remise"]

    # --- backlog : clôture d'une fiche de journal
    at.text_input(key="smb_q").set_value("")
    at.multiselect(key="smb_prio").set_value(["CRITIQUE"]).run()
    avant = int((at.session_state["_gmao_tables"]["defauts"]["resultat"] == "Clôturé").sum())
    at.selectbox(key="smb_sel").set_value(0).run()
    at.selectbox(key="smb_st_0").set_value("Clôturé")
    ok, err = _valider(at, "Mettre à jour")
    assert ok and not err
    d = at.session_state["_gmao_tables"]["defauts"]
    assert int((d["resultat"] == "Clôturé").sum()) == avant + 1
    assert d["commentaire"].astype(str).str.contains("Mis à jour dans l'application").sum() == 1


def test_parcours_arrets(app):
    """Déclaration d'un arrêt, refus d'un doublon, remise en marche, arrêt ouvert par un état saisi, arrêt lié à une fiche."""
    import pandas as pd
    at = app
    arrets = lambda: at.session_state["gmao_arrets"]            # noqa: E731
    etats = lambda: at.session_state["gmao_etats_saisis"]       # noqa: E731
    sites = at.selectbox(key="sma_site_0").options
    k = _cle(sites[5])
    # --- déclaration : refusée sans cause, puis acceptée ; la centrale passe à l'arrêt
    at.selectbox(key="sma_site_0").set_value(k)
    ok, err = _valider(at, "Déclarer l'arrêt")
    assert not ok and "cause" in err[0]
    at.selectbox(key="sma_site_0").set_value(k)
    at.selectbox(key="sma_c_0").set_value("Vandalisme")
    at.date_input(key="sma_j_0").set_value((pd.Timestamp.now() - pd.Timedelta(days=3)).date())
    ok, err = _valider(at, "Déclarer l'arrêt")
    assert ok and not err, err
    a = arrets().iloc[-1]
    assert a["cle_site"] == k and pd.isna(a["fin"]) and a["cause"] == "Vandalisme" and not a["date_a_verifier"]
    assert etats().iloc[-1]["etat"] == "À l'arrêt" and etats().iloc[-1]["cle_site"] == k
    # --- un second arrêt sur la même centrale est refusé
    at.selectbox(key="sma_site_1").set_value(k)
    at.selectbox(key="sma_c_1").set_value("Météo")
    ok, err = _valider(at, "Déclarer l'arrêt")
    assert not ok and "déjà en cours" in err[0] and len(arrets()) == 1
    # --- remise en marche : la centrale repasse en service, la disponibilité reste calculable
    ok, err = _valider(at, "Valider")
    assert ok and not err, err
    a = arrets().iloc[-1]
    assert pd.notna(a["fin"]) and a["fin"] > a["debut"] and etats().iloc[-1]["etat"] == "Fonctionnement 24 h/24"
    dispo = {m.label: m.value for m in at.metric if m.label.startswith("Disponibilité")}
    assert set(dispo) == {"Disponibilité 30 j", "Disponibilité 90 j"} and all(v.endswith("%") for v in dispo.values())

    # --- un état « À l'arrêt » saisi dans le parc ouvre un arrêt ; le retour en service le clôt
    k2 = _cle(sites[8])
    at.selectbox(key="smp_site").set_value(k2).run()
    at.selectbox(key=f"smp_e_{k2}_0").set_value("À l'arrêt")
    at.selectbox(key=f"smp_c_{k2}_0").set_value("Météo")
    ok, err = _valider(at, "Enregistrer l'état")
    assert ok and len(arrets()) == 2 and arrets().iloc[-1]["cle_site"] == k2 and pd.isna(arrets().iloc[-1]["fin"])
    at.selectbox(key=f"smp_e_{k2}_1").set_value("Fonctionnement 24 h/24")
    ok, err = _valider(at, "Enregistrer l'état")
    assert ok and pd.notna(arrets().iloc[-1]["fin"])

    # --- fiche avec « déclarer aussi un arrêt » : l'arrêt est lié à la fiche et se clôt avec elle
    at.selectbox(key="smf_site_0").set_value(_cle(at.selectbox(key="smf_site_0").options[12]))
    at.selectbox(key="smf_cat_0").set_value(at.selectbox(key="smf_cat_0").options[0])
    at.selectbox(key="smf_mat_0").set_value("Batterie")
    at.text_area(key="smf_desc_0").set_value("Arrêt lié à une fiche (essai)")
    at.checkbox(key="smf_arret_0").check()
    ok, err = _valider(at, "Enregistrer la fiche")
    assert ok and not err, err
    bi = at.session_state["gmao_bi"].iloc[-1]
    a = arrets().iloc[-1]
    assert len(arrets()) == 3 and a["source"] == f"Fiche {bi['id']}" and pd.isna(a["fin"]) and bool(bi["centrale_arret"])
    at.text_input(key="smb_q").set_value("essai").run()
    at.selectbox(key="smb_sel").set_value(0).run()
    at.selectbox(key="smb_st_0").set_value("Clôturé")
    ok, err = _valider(at, "Mettre à jour")
    assert ok and pd.notna(arrets().iloc[-1]["fin"])
