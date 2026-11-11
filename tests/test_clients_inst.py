import pandas as pd

from utils import clients_inst as ci


def test_montant_en_lettres():
    assert ci.en_lettres(143100) == "cent quarante-trois mille cent"
    assert ci.en_lettres(80000) == "quatre-vingt mille"
    assert ci.en_lettres(2_480_000) == "deux millions quatre cent quatre-vingt mille"
    assert ci.en_lettres(71) == "soixante et onze"


def test_import_et_soldes():
    raw = pd.DataFrame({"Date": ["02/10/2026", "15/10/2026", None], "Client": ["MTN Cameroon", "IHS Cameroon", "MTN"],
                        "Type": ["Recharge token", "Achat compteur", "Recharge"], "kWh": ["1 000", "2", "5"],
                        "Montant": ["120 000", "150000", "600"]})
    x = ci.preparer_import(raw, ci.deviner_colonnes(raw), "MTN", "Recharge", {"MTN": "MTN Cameroon", "IHS": "IHS Cameroon"})
    assert list(x["client"]) == ["MTN", "IHS"] and list(x["type"]) == ["Recharge", "Achat de compteurs"]
    assert x["montant_ht"].sum() == 270000
    fac = ci._normaliser("ci_factures", pd.DataFrame([
        {"id": "FAC-2026-0001", "date": "2026-09-01", "client": "MTN", "montant_ttc": 100000, "echeance": "2026-10-01", "annulee": False},
        {"id": "FAC-2026-0002", "date": "2026-10-01", "client": "MTN", "montant_ttc": 50000, "echeance": "2026-12-01", "annulee": False}]))
    pay = ci._normaliser("ci_paiements", pd.DataFrame([{"id": "PAY-1", "date": "2026-09-20", "facture_id": "FAC-2026-0001", "montant": 100000}]))
    f = ci.factures_avec_soldes(fac, pay, pd.Timestamp("2026-11-10"))
    assert list(f["statut"]) == ["Payée", "Émise"] and f["reste"].sum() == 50000 and f["delai_paiement_j"].iloc[0] == 19
