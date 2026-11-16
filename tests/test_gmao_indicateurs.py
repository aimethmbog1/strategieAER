"""Tests des règles métier du suivi de la maintenance des centrales (utils/gmao_indicateurs.py) :
un test par règle et par indicateur. Aucune donnée réelle : les jeux d'essai sont fabriqués ici."""
import pandas as pd
import pytest

from utils import gmao_indicateurs as gi

AUJ = pd.Timestamp("2026-11-16")
J = lambda n: AUJ - pd.Timedelta(days=n)  # noqa: E731


def fiche(**k):
    base = {"source": "Journal 2026", "ref": None, "cle_site": "a", "site": "A", "phase": "Phase 2", "region": "Nord",
            "date_constat": J(10), "date_cloture": pd.NaT, "ouvert": True, "priorite": "MAJEUR", "categorie": "Champ PV",
            "materiel": "Onduleur", "description": "", "qte_affectee": 0, "qte_remplacee": 0, "lineaire": False,
            "site_arret_au_constat": False, "jours_prevus": None}
    return base | k


def fiches(*lignes, delais=None):
    return gi.completer_fiches(pd.DataFrame(list(lignes), columns=gi.COLONNES_FICHES), AUJ, delais)


def sites(*lignes):
    cols = ["cle_site", "site", "phase", "region", "kwc", "etat", "cause", "zone", "responsable"]
    return pd.DataFrame([dict(zip(cols, l)) for l in lignes], columns=cols)


# ----------------------------------------------------------------------------- priorités, délais, échéances
@pytest.mark.parametrize("brut,att", [("CRITICAL", "CRITIQUE"), ("Critique", "CRITIQUE"), ("MAJOR", "MAJEUR"),
                                      ("Majeure", "MAJEUR"), ("MINOR", "MINEUR"), ("Urgente", "URGENT"),
                                      ("URGENT", "URGENT"), (None, "Non renseignée"), ("???", "Non renseignée")])
def test_priorite_normalisee(brut, att):
    assert gi.priorite_normalisee(brut) == att


def test_delais_par_priorite():
    assert gi.delai_resolution("URGENT") == 2 and gi.delai_resolution("CRITIQUE") == 7
    # MAJEUR et MINEUR : « à compléter » → on garde le nombre de jours prévu de la fiche, sinon pas de délai
    assert gi.delai_resolution("MAJEUR") is None and gi.delai_resolution("MAJEUR", jours_prevus=30) == 30
    assert gi.delai_resolution("MAJEUR", {"MAJEUR": 15}, jours_prevus=30) == 15      # le paramètre l'emporte
    assert gi.delai_resolution("CRITIQUE", jours_prevus=60) == 7


def test_echeance_conforme_au_prototype():
    # capture « Backlog » : CRITIQUE constaté le 09/01/2025 → échéance 16/01/2025, retard 669 j au 16/11/2026
    f = fiches(fiche(priorite="CRITIQUE", date_constat=pd.Timestamp("2025-01-09")))
    assert f["echeance"].iloc[0] == pd.Timestamp("2025-01-16") and f["retard_j"].iloc[0] == 669 and f["hors_delai"].iloc[0]
    # capture « Nouvelle fiche » : URGENT constaté le 16/11/2026 → échéance 18/11/2026
    assert gi.echeance(AUJ, "URGENT") == pd.Timestamp("2026-11-18")
    assert gi.echeance(None, "URGENT") is None and gi.echeance(AUJ, "MAJEUR") is None


def test_hors_delai_seulement_si_ouverte_et_echeance_depassee():
    f = fiches(fiche(priorite="URGENT", date_constat=J(1)),                          # échéance demain
               fiche(priorite="URGENT", date_constat=J(2)),                          # échéance aujourd'hui : pas en retard
               fiche(priorite="URGENT", date_constat=J(3)),                          # 1 jour de retard
               fiche(priorite="URGENT", date_constat=J(30), ouvert=False, date_cloture=J(1)),   # clôturée
               fiche(priorite="MAJEUR", date_constat=J(900)),                        # sans délai : jamais hors délai
               fiche(priorite="URGENT", date_constat=pd.NaT))                        # sans date
    assert list(f["hors_delai"]) == [False, False, True, False, False, False]
    assert f["retard_j"].iloc[2] == 1


# ----------------------------------------------------------------------------- indicateurs
def test_taux_de_cloture_et_backlog():
    f = fiches(fiche(), fiche(), fiche(priorite="CRITIQUE", date_constat=J(100)),
               fiche(ouvert=False, date_cloture=J(2)))
    k = gi.indicateurs_maintenance(f)
    assert k["enregistrees"] == 4 and k["backlog"] == 3 and k["cloturees"] == 1 and k["taux_cloture"] == 25
    assert k["hors_delai"] == 1 and k["pct_hors_delai"] == pytest.approx(100 / 3)
    assert k["ouvertes_sans_echeance"] == 2 and k["urgents_critiques_ouverts"] == 1
    assert k["age_median_j"] == 10


def test_mttr_ecarte_les_clotures_le_jour_meme_et_les_compte():
    clos = lambda constat, cloture: fiche(ouvert=False, date_constat=constat, date_cloture=cloture)  # noqa: E731
    f = fiches(clos(J(50), J(50)), clos(J(40), J(40)), clos(J(30), J(30)),      # 3 clôtures le jour du constat
               clos(J(20), J(10)), clos(J(60), J(30)),                           # 10 j et 30 j
               clos(J(10), J(15)),                                               # clôture avant le constat
               clos(J(10), pd.NaT), fiche())                                     # sans date ; fiche ouverte
    m = gi.mttr_median(f)
    assert m == {"mttr": 20.0, "retenues": 2, "meme_jour": 3, "sans_date": 1, "incoherentes": 1, "cloturees": 7,
                 "mttr_avec_meme_jour": 0.0}
    assert gi.mttr_median(fiches(fiche()))["mttr"] is None


def test_respect_du_delai_sur_clotures_datees():
    clos = lambda n_constat, n_cloture, **k: fiche(ouvert=False, date_constat=J(n_constat), date_cloture=J(n_cloture), **k)  # noqa: E731
    f = fiches(clos(20, 15, priorite="CRITIQUE"),      # 5 j ≤ 7 : dans le délai
               clos(20, 5, priorite="CRITIQUE"),       # 15 j > 7 : hors délai
               clos(20, 5, priorite="MAJEUR"),         # sans échéance : hors base
               clos(20, 5, priorite="MAJEUR", jours_prevus=30))
    k = gi.indicateurs_maintenance(f)
    assert k["respect_delai_base"] == 3 and k["respect_delai"] == pytest.approx(200 / 3)


def test_recidivistes_constats_arret_et_batteries():
    f = fiches(*[fiche(cle_site="a") for _ in range(5)], *[fiche(cle_site="b") for _ in range(4)],
               fiche(cle_site="c", site_arret_au_constat=True, materiel="Batterie", qte_affectee=10, qte_remplacee=4))
    k = gi.indicateurs_maintenance(f, seuil_recidive=5)
    assert k["recidivistes"] == 1 and gi.indicateurs_maintenance(f, seuil_recidive=4)["recidivistes"] == 2
    assert k["constats_arret"] == 1 and k["pct_constats_arret"] == 10
    assert (k["batteries_affectees"], k["batteries_remplacees"], k["pct_batteries"]) == (10, 4, 40)


def test_materiel_vide_signale_jamais_nan():
    f = fiches(fiche(materiel="nan"), fiche(materiel=None), fiche(materiel="  "), fiche(materiel="MDU"))
    assert list(f["materiel"]) == ["Non renseigné"] * 3 + ["MDU"]
    assert gi.indicateurs_maintenance(f)["materiel_non_renseigne"] == 3


def test_filtre_de_periode_compte_les_fiches_sans_date():
    f = fiches(fiche(date_constat=J(5)), fiche(date_constat=J(400)), fiche(date_constat=pd.NaT),
               fiche(date_constat=J(5), region="Est"))
    v, sans_date = gi.filtrer_fiches(f, debut=J(30), fin=AUJ)
    assert len(v) == 2 and sans_date == 1
    v, sans_date = gi.filtrer_fiches(f, regions=["Est"])
    assert len(v) == 1 and sans_date == 0
    assert len(gi.filtrer_fiches(f, statut="Clôturé")[0]) == 0 and len(gi.filtrer_fiches(f, sites={"zzz"})[0]) == 0


# ----------------------------------------------------------------------------- états et puissance
@pytest.mark.parametrize("etat,detail,att", [
    ("Fonctionnement H24", None, gi.H24), ("Remise en marche", None, gi.H24), ("Arret avant 18H", None, gi.AVANT_18H),
    ("Apres 18H", None, gi.APRES_18H), ("En Arrêt", None, gi.ARRET), ("Arret de marche", None, gi.ARRET),
    ("Fonctionnement H24", "Fonctionne à vide", gi.A_VIDE), ("inconnu", None, gi.NON_RENSEIGNE), (None, None, gi.NON_RENSEIGNE)])
def test_etat_detaille(etat, detail, att):
    assert gi.etat_detaille(etat, detail) == att


PARC = sites(("a", "A", "Phase 1", "Nord", 100.0, gi.H24, None, "ZONE1", "R1"),
             ("b", "B", "Phase 1", "Nord", 50.0, gi.A_VIDE, "Réseau non disponible", "ZONE1", "R1"),
             ("c", "C", "Phase 1", "Est", 30.0, gi.ARRET, "Batteries défectueuses", "ZONE2", "R2"),
             ("d", "D", "Phase 2", "Est", 80.0, gi.APRES_18H, None, "ZONE2", "R2"),
             ("e", "E", "Phase 2", "Est", 40.0, gi.AVANT_18H, None, "ZONE2", "R2"),
             ("p", "P", "Phase 3", "Sud", 200.0, gi.NON_MES, None, None, None))


def test_tableau_des_etats_hors_phase_3():
    t = gi.tableau_etats(PARC).set_index(["phase", "etat"])
    assert t.at[("Phase 1", gi.H24), "nb"] == 1 and t.at[("Phase 1", gi.A_VIDE), "kwc"] == 50
    assert t.at[("Phase 1", gi.ARRET), "pct"] == pytest.approx(100 / 3)
    assert t.at[("Total", gi.H24), "sites_phase"] == 5            # la Phase 3 n'est pas comptée
    assert t.loc["Total"]["nb"].sum() == 5 and "Phase 3" not in t.index.get_level_values(0)


def test_puissance_du_parc():
    p = gi.puissance_parc(PARC, cible_kwc=1000)
    assert p["installee"] == 500 and p["en_service"] == 270 and p["partiel"] == 120 and p["arret"] == 30
    assert p["non_mes"] == 200 and p["sites_non_mes"] == 1 and p["sites_arret"] == 1
    assert p["pct_cible"] == 27 and p["ecart_cible"] == 730
    ph = p["par_phase"].set_index("Phase")
    assert ph.at["Phase 1", "% exploité"] == pytest.approx(100 * 150 / 180) and pd.isna(ph.at["Phase 3", "% exploité"])
    assert ph.at["Total", "% exploité"] == pytest.approx(100 * 270 / 300)   # sur la puissance mise en service
    assert gi.puissance_parc(PARC)["cible"] == 500                          # sans cible : la puissance installée


# ----------------------------------------------------------------------------- score d'exposition
def test_score_plafonds_et_motifs():
    # capture : 16 fiches récentes (plafond 20) + 1 arrêt (4) + visite de plus de 6 mois (3) = 27 points
    pts, motifs = gi.score_exposition({"MAJEUR": 16}, 1, 186)
    assert pts == 27 and len(motifs) == 3
    # capture : 12 fiches dont 2 urgentes/critiques, visite récente → plafond 20, +3 si visite ancienne = 23
    assert gi.score_exposition({"CRITIQUE": 2, "MAJEUR": 10}, 0, 250)[0] == 23
    assert gi.score_exposition({"URGENT": 1, "CRITIQUE": 1, "MAJEUR": 1, "MINEUR": 1, "Non renseignée": 1}, 0, 10)[0] == 8 + 5 + 2 + 1 + 1
    assert gi.score_exposition({}, 5, 10)[0] == 12                         # arrêts : 4 chacun, plafond 12
    assert gi.score_exposition({}, 0, None) == (3, ["jamais visité : 3 pt"])
    assert gi.score_exposition({}, 0, 10) == (0, [])


def test_score_signaux_supervision_et_poids_configurables():
    assert gi.score_exposition({}, 0, 1, {"service_inf_95": True, "batterie_vide_3j": True,
                                          "ecart_cellules_100mv": True, "rendement_stockage_inf_80": True})[0] == 8 + 6 + 5 + 3
    assert gi.score_exposition({}, 0, 1, {"service_inf_95": False})[0] == 0
    assert gi.score_exposition({}, 0, 1, supervision="défaillante")[0] == 6
    assert gi.score_exposition({}, 0, 1, supervision="déconnectée")[0] == 4
    poids = {**gi.POIDS_DEFAUT, "fiche": {"URGENT": 1, "CRITIQUE": 1, "MAJEUR": 1, "autre": 1}, "plafond_fiches": 3,
             "sans_visite": 10, "sans_visite_mois": 1}
    assert gi.score_exposition({"URGENT": 9}, 0, 45, poids=poids)[0] == 3 + 10


def test_scores_des_sites_en_service():
    f = fiches(fiche(cle_site="a", priorite="URGENT", date_constat=J(30)),
               fiche(cle_site="a", priorite="MAJEUR", date_constat=J(500)),        # ancienne : non comptée
               fiche(cle_site="a", priorite="MAJEUR", date_constat=J(30), ouvert=False, date_cloture=J(5)),
               fiche(cle_site="c", priorite="URGENT", date_constat=J(30)))         # site à l'arrêt : hors tableau
    arrets = pd.DataFrame({"cle_site": ["a", "a", "a"], "date": [J(20), J(100), J(800)]})
    visites = pd.DataFrame({"cle_site": ["a", "b"], "date": [J(10), J(400)]})
    s = gi.scores_sites(PARC, f, arrets, visites, AUJ, supervision={"b": "déconnectée"}).set_index("cle_site")
    assert set(s.index) == {"a", "b"}                                              # H24 et « à vide » seulement
    assert s.at["a", "Points"] == 8 + 2 * 4 and "ancienne" in s.at["a", "Motifs"]
    assert s.at["b", "Points"] == 3 + 4 and s.index[0] == "a"


# ----------------------------------------------------------------------------- priorités d'intervention
def test_sites_a_remettre_en_service_et_sans_fiche():
    f = fiches(fiche(cle_site="c", date_constat=J(100)), fiche(cle_site="c", date_constat=J(40)),
               fiche(cle_site="d", ouvert=False, date_cloture=J(1)))
    r = gi.a_remettre_en_service(PARC, f).set_index("cle_site")
    assert list(r.index) == ["c", "d", "e"]                                        # à l'arrêt d'abord, puis par puissance
    assert r.at["c", "Suivi"] == "2 fiche(s) · 100 j" and r.at["d", "Suivi"] == "sans fiche"
    assert r.at["c", "Cause déclarée"] == "Batteries défectueuses"


def test_priorites_d_intervention():
    f = fiches(fiche(cle_site="a", priorite="CRITIQUE", date_constat=J(30)), fiche(cle_site="c"))
    visites = pd.DataFrame({"cle_site": ["a", "d"], "date": [J(10), J(300)]})
    sc = gi.scores_sites(PARC, f, pd.DataFrame(columns=["cle_site", "date"]), visites, AUJ)
    p = gi.priorites_intervention(PARC, f, sc, visites, AUJ)
    assert p["en_service_h24"] == 2 and p["en_service"] == 4 and p["tres_exposes"] == 0
    assert p["a_remettre"] == 3 and p["a_remettre_sans_fiche"] == 2 and p["phase1_arret"] == 1
    assert p["sans_visite"] == 3 and p["jamais_visites"] == 2                      # b, e jamais ; d il y a 300 j
    assert p["urgents_critiques_hors_delai"] == 1


def test_interruptions_non_signalees():
    f = fiches(fiche(cle_site="a", site_arret_au_constat=True, date_constat=J(20)),     # en service + constat d'arrêt récent
               fiche(cle_site="a", site_arret_au_constat=True, date_constat=J(200)),    # trop ancien
               fiche(cle_site="d", site_arret_au_constat=True, date_constat=J(5), ouvert=False, date_cloture=J(1)),
               fiche(cle_site="c", site_arret_au_constat=True, date_constat=J(5)))      # déjà déclaré à l'arrêt
    r = gi.interruptions_non_signalees(PARC, f, AUJ, jours=90, deconnectees={"b": J(12), "c": J(12)})
    assert set(r["cle_site"]) == {"a", "b"}
    assert "1 fiche(s)" in r.set_index("cle_site").at["a", "Indice"] and r.set_index("cle_site").at["b", "État déclaré"] == gi.A_VIDE
    assert gi.interruptions_non_signalees(PARC, fiches(fiche()), AUJ).empty


# ----------------------------------------------------------------------------- séries des graphiques
def test_backlog_par_anciennete():
    f = fiches(fiche(date_constat=J(10)), fiche(date_constat=J(29)), fiche(date_constat=J(30)),
               fiche(date_constat=J(100), priorite="CRITIQUE"), fiche(date_constat=J(400), priorite="URGENT"),
               fiche(date_constat=J(400)), fiche(date_constat=pd.NaT), fiche(ouvert=False, date_cloture=J(1)))
    t = gi.backlog_par_anciennete(f).set_index("Âge")
    assert list(t.index) == gi.TRANCHES_AGE
    assert list(t["Dans le délai"]) == [2, 1, 0, 0, 1] and list(t["Hors délai"]) == [0, 0, 1, 0, 1]


def test_defauts_par_mois_et_repartitions():
    f = fiches(fiche(date_constat=pd.Timestamp("2026-03-05")), fiche(date_constat=pd.Timestamp("2026-03-20"), ouvert=False,
                                                                     date_cloture=pd.Timestamp("2026-04-01")),
               fiche(date_constat=pd.Timestamp("2026-05-02"), region="Est", priorite="URGENT"), fiche(date_constat=pd.NaT))
    m = gi.defauts_par_mois(f)
    assert len(m) == 2 and list(m["Ouverts"]) == [1, 1] and list(m["Clôturés"]) == [1, 0]
    r = gi.repartition(f, "region", "Région").set_index("Région")
    assert r.at["Nord", "Défauts"] == 3 and r.at["Nord", "Clôturés"] == 1 and r.at["Est", "Hors délai"] == 1


def test_top_sites_et_materiel():
    f = fiches(*[fiche(cle_site="c", site="C") for _ in range(3)], fiche(cle_site="a", site="A"),
               fiche(materiel="Batterie", qte_affectee=10, qte_remplacee=4),
               fiche(materiel="Batterie", qte_affectee=5, qte_remplacee=9),
               fiche(materiel="Câble PD", qte_affectee=300), fiche(materiel="Ligne Electrique", qte_affectee=80),
               fiche(materiel="Câbles photovoltaïques souterrains", qte_affectee=50),
               fiche(materiel=None, qte_affectee=2))
    t = gi.top_sites(f, PARC, n=2)
    assert list(t["Site"]) == ["A", "C"] and t["État"].iloc[1] == gi.ARRET
    m = gi.materiel_affecte_remplace(f).set_index("Matériel")
    assert set(m.index) == {"Batterie", "Non renseigné"}                          # câbles et lignes exclus
    assert (m.at["Batterie", "Affecté"], m.at["Batterie", "Remplacé"], m.at["Batterie", "Reste à fournir"]) == (15, 13, 2)
    assert gi.est_lineaire("câble d'alimentation") and gi.est_lineaire("PM Cables") and not gi.est_lineaire("Poteau en bois")


def test_etat_par_region():
    t = gi.etat_par_region(PARC).set_index("Région")
    assert t.at["Nord", "En service H24"] == 2 and t.at["Est", "Service partiel"] == 2 and t.at["Sud", gi.NON_MES] == 1


# ----------------------------------------------------------------------------- conversion des sources
def test_fiches_depuis_journaux_et_bi():
    d = pd.DataFrame({"source": ["Journal 2026"] * 2, "num": [1, 2], "cle_site": ["a", "b"], "site": ["A", "B"],
                      "phase": ["Phase 1"] * 2, "region": ["Nord"] * 2, "date_incident": [J(9), J(8)],
                      "date_achevement": [J(1), J(1)], "resultat": ["Clôturé", "En attente"], "priorite": ["CRITICAL", "MAJOR"],
                      "categorie": ["Champ PV"] * 2, "materiel": ["MDU", "nan"], "description": ["x", "y"],
                      "qte_affectee": [1, None], "qte_remplacee": [1, None], "lineaire": [False, False],
                      "etat_arrivee": ["En Arrêt", "En Marche"], "jours_prevus": [30, 15]})
    f = fiches(*gi.fiches_depuis_journaux(d).to_dict("records"))
    assert list(f["ouvert"]) == [False, True] and list(f["priorite"]) == ["CRITIQUE", "MAJEUR"]
    assert pd.isna(f["date_cloture"].iloc[1])                 # une fiche ouverte n'a pas de date de clôture
    assert list(f["site_arret_au_constat"]) == [True, False] and f["delai_j"].iloc[0] == 8
    bi = pd.DataFrame({"id": ["BI-1", "BI-2", "BI-3", "BI-4"], "type": ["Corrective", "Préventive", "Corrective", "Corrective"],
                       "statut": ["En cours", "Planifié", "Annulé", "Clôturé"], "site": ["A"] * 4, "phase": ["Phase 1"] * 4,
                       "region": ["Nord"] * 4, "date_creation": [J(5)] * 4, "date_prevue": [J(2), None, None, None],
                       "date_fin": [None, None, None, J(1)], "priorite": ["Urgente", "Mineure", "Majeure", "Critique"],
                       "systeme": ["Champ PV"] * 4, "equipement": [None, None, None, "MDU"], "description": ["d"] * 4,
                       "centrale_arret": [True, False, False, False]})
    b = gi.fiches_depuis_bi(bi, ["À planifier", "Planifié", "En cours", "En attente de pièces"])
    assert list(b["ref"]) == ["BI-1", "BI-4"] and list(b["ouvert"]) == [True, False]      # préventif et annulé écartés
    assert list(b["priorite"]) == ["URGENT", "CRITIQUE"] and b["jours_prevus"].iloc[0] == 3
    assert gi.fiches_depuis_bi(None, []).empty and gi.fiches_depuis_journaux(None).empty
