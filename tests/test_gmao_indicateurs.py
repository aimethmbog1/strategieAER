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


# ============================================================================= lot 2 : parc, backlog, fiche
FICHE_OK = {"site": "A", "date_constat": J(3), "priorite": "URGENT", "categorie": "Champ PV", "materiel": "MDU",
            "description": "MDU en défaut", "qte_affectee": 2, "qte_remplacee": 1, "cloturee": False, "date_cloture": None}


def test_fiche_valide():
    assert gi.controler_fiche(FICHE_OK, AUJ) == []
    assert gi.controler_fiche(FICHE_OK | {"cloturee": True, "date_cloture": J(1)}, AUJ) == []


@pytest.mark.parametrize("modif,mot", [
    ({"materiel": "nan"}, "matériel"), ({"materiel": "  "}, "matériel"), ({"materiel": None}, "matériel"),
    ({"site": None}, "site"), ({"description": ""}, "description"), ({"categorie": None}, "catégorie"),
    ({"priorite": "Non renseignée"}, "priorité"), ({"date_constat": None}, "date de constat"),
    ({"date_constat": AUJ + pd.Timedelta(days=1)}, "futur"), ({"qte_remplacee": 5}, "dépasse"),
    ({"qte_affectee": -1, "qte_remplacee": 0}, "négatives"), ({"cloturee": True, "date_cloture": None}, "date de clôture"),
    ({"cloturee": True, "date_cloture": J(10)}, "précède"), ({"cloturee": True, "date_cloture": AUJ + pd.Timedelta(days=2)}, "futur")])
def test_fiche_refusee(modif, mot):
    err = gi.controler_fiche(FICHE_OK | modif, AUJ)
    assert len(err) == 1 and mot in err[0]


def test_valeurs_vides():
    assert all(gi.est_vide(x) for x in (None, float("nan"), "", "  ", "nan", "NaN", "None", "—", "Non renseigné"))
    assert not gi.est_vide("Batterie") and not gi.est_vide(0)


def test_controle_de_l_etat_saisi():
    assert gi.controler_etat("A", gi.H24, AUJ, AUJ) == []
    assert gi.controler_etat("A", gi.ARRET, J(2), AUJ, "Vandalisme") == []
    assert "cause" in gi.controler_etat("A", gi.ARRET, AUJ, AUJ)[0]
    assert "cause" in gi.controler_etat("A", gi.APRES_18H, AUJ, AUJ, " ")[0]
    assert "futur" in gi.controler_etat("A", gi.H24, AUJ + pd.Timedelta(days=1), AUJ)[0]
    assert len(gi.controler_etat(None, "Autre", None, AUJ)) == 3


def test_etat_saisi_remplace_celui_du_journal():
    saisies = pd.DataFrame([
        {"horodatage": J(5), "cle_site": "a", "site": "A", "etat": gi.ARRET, "cause": "Vandalisme", "date_effet": J(6), "commentaire": None, "auteur": "x"},
        {"horodatage": J(1), "cle_site": "a", "site": "A", "etat": gi.A_VIDE, "cause": "Réseau", "date_effet": J(2), "commentaire": None, "auteur": "x"},
        {"horodatage": J(0), "cle_site": "a", "site": "A", "etat": gi.ARRET, "cause": "Ancien", "date_effet": J(30), "commentaire": None, "auteur": "x"},
        {"horodatage": J(1), "cle_site": "p", "site": "P", "etat": gi.H24, "cause": None, "date_effet": J(1), "commentaire": None, "auteur": "x"}],
        columns=gi.COLONNES_ETATS_SAISIS)
    s = gi.appliquer_etats_saisis(PARC, saisies).set_index("cle_site")
    assert s.at["a", "etat"] == gi.A_VIDE and s.at["a", "cause"] == "Réseau"        # date d'effet la plus récente
    assert s.at["a", "etat_date"] == J(2) and s.at["a", "etat_source"] == "Saisie"
    assert s.at["p", "etat"] == gi.H24                                             # un site de Phase 3 mis en service
    assert s.at["c", "etat"] == gi.ARRET and s.at["c", "etat_source"] == "Journal" and pd.isna(s.at["c", "etat_date"])
    vide = gi.appliquer_etats_saisis(PARC, None).set_index("cle_site")
    assert vide.at["p", "etat_source"] == "Référentiel" and list(vide["etat"]) == list(PARC["etat"])


def test_backlog_tri_et_filtres():
    f = fiches(fiche(cle_site="a", priorite="MAJEUR", date_constat=J(900), description="poteau tombé"),
               fiche(cle_site="c", priorite="CRITIQUE", date_constat=J(50), region="Est"),
               fiche(cle_site="c", priorite="CRITIQUE", date_constat=J(200), region="Est"),
               fiche(cle_site="a", priorite="URGENT", date_constat=J(1)),
               fiche(cle_site="a", priorite="URGENT", date_constat=pd.NaT),
               fiche(cle_site="a", ouvert=False, date_cloture=J(1)))
    zones = {"a": "ZONE1", "c": "ZONE2"}
    b = gi.backlog(f, zone_par_site=zones)
    assert len(b) == 5 and list(b["priorite"]) == ["URGENT", "URGENT", "CRITIQUE", "CRITIQUE", "MAJEUR"]
    assert pd.isna(b["date_constat"].iloc[1]) and b["age_j"].iloc[2] == 200        # la plus ancienne d'abord
    assert len(gi.backlog(f, delai="Hors délai", zone_par_site=zones)) == 2
    assert len(gi.backlog(f, delai="Dans le délai", zone_par_site=zones)) == 1      # URGENT d'hier : échéance demain
    assert len(gi.backlog(f, delai="Sans échéance", zone_par_site=zones)) == 2      # MAJEUR sans délai ; URGENT sans date
    assert len(gi.backlog(f, zones=["ZONE2"], zone_par_site=zones)) == 2 and len(gi.backlog(f, regions=["Est"])) == 2
    assert len(gi.backlog(f, recherche="POTEAU")) == 1 and gi.backlog(f, priorites=["MINEUR"]).empty


def test_synthese_par_region():
    f = fiches(fiche(cle_site="c"), fiche(cle_site="c"), fiche(cle_site="a"), fiche(cle_site="d", ouvert=False, date_cloture=J(1)))
    t = gi.synthese_par_region(PARC, f).set_index("Région")
    assert (t.at["Nord", "Sites"], t.at["Nord", "Installée (kWc)"], t.at["Nord", "En service (kWc)"]) == (2, 150, 150)
    assert t.at["Nord", "% exploité"] == 100 and t.at["Nord", "Défauts ouverts"] == 1
    assert t.at["Est", "À l'arrêt"] == 1 and t.at["Est", "% exploité"] == pytest.approx(100 * 120 / 150) and t.at["Est", "Défauts ouverts"] == 2
    assert pd.isna(t.at["Sud", "% exploité"])                                      # rien n'est mis en service


def test_table_des_sites():
    f = fiches(fiche(cle_site="c", priorite="URGENT", date_constat=J(40)), fiche(cle_site="c", date_constat=J(10)),
               fiche(cle_site="a", ouvert=False, date_constat=J(70), date_cloture=J(60)))
    arrets = pd.DataFrame({"cle_site": ["c", "c", "c"], "date": [J(10), J(40), J(700)]})
    visites = pd.DataFrame({"cle_site": ["c", "c"], "date": [J(40), J(10)]})
    t = gi.table_sites(PARC, f, arrets, visites, AUJ.year).set_index("cle_site")
    assert (t.at["c", "Ouverts"], t.at["c", "Hors délai"], t.at["c", f"Arrêts {AUJ.year}"]) == (2, 1, 2)
    assert t.at["c", "Dernière visite"] == J(10) and t.at["c", "Dernier défaut"] == J(10)
    assert t.at["a", "Ouverts"] == 0 and t.at["a", "Dernier défaut"] == J(70) and pd.isna(t.at["p", "Dernière visite"])
    assert len(t) == len(PARC)


# ============================================================================= lot 3 : arrêts et disponibilité
H = lambda n: AUJ - pd.Timedelta(hours=n)  # noqa: E731


def episodes(*lignes):
    """(cle_site, début, fin, date à vérifier, cause, équipe)"""
    d = pd.DataFrame([{"id": f"AR-{i}", "cle_site": k, "site": k.upper(), "debut": deb, "fin": fin, "cause": cause,
                       "commentaire": None, "equipe": eq, "source": "Saisie", "date_a_verifier": verif, "auteur": "x",
                       "horodatage": AUJ, "remise_par": None}
                      for i, (k, deb, fin, verif, cause, eq) in enumerate(lignes)], columns=gi.COLONNES_ARRETS)
    for c in ("debut", "fin"):
        d[c] = pd.to_datetime(d[c])
    d["date_a_verifier"] = d["date_a_verifier"].astype(bool)
    return d


def test_heures_indisponibles_union_et_bornes():
    d, f = J(10), AUJ                                            # période de 240 h
    assert gi.heures_indisponibles([(J(2), J(1))], d, f) == 24
    assert gi.heures_indisponibles([(J(2), J(1)), (J(2), J(1))], d, f) == 24             # doublon : compté une fois
    assert gi.heures_indisponibles([(J(4), J(2)), (J(3), J(1))], d, f) == 72             # chevauchement : union
    assert gi.heures_indisponibles([(J(20), J(9))], d, f) == 24                          # rogné au début de la période
    assert gi.heures_indisponibles([(J(1), None)], d, f) == 24                           # en cours : jusqu'à la fin
    assert gi.heures_indisponibles([(None, None)], d, f) == 240                          # début inconnu, en cours
    assert gi.heures_indisponibles([(J(30), J(20))], d, f) == 0 and gi.heures_indisponibles([], d, f) == 0


def test_disponibilite_du_parc():
    per = {"a", "b", "c", "d"}                                   # 4 sites × 10 jours = 960 h
    ep = episodes(("a", J(2), J(1), False, "Vandalisme", "E1"),              # 24 h
                  ("b", J(5), None, False, "Météo", None),                   # en cours : 120 h
                  ("z", J(5), None, False, "Hors périmètre", None))
    r = gi.disponibilite_parc(ep, per, set(), J(10), AUJ)
    assert r["heures_arret"] == 144 and r["disponibilite"] == pytest.approx(100 * (1 - 144 / 960))
    assert r["sites"] == 4 and r["sites_avec_arret"] == 2 and r["sites_toute_la_periode"] == 0
    # un site déclaré à l'arrêt sans arrêt saisi est indisponible sur toute la période
    r = gi.disponibilite_parc(ep, per, {"c", "hors"}, J(10), AUJ)
    assert r["heures_arret"] == 144 + 240 and r["sites_toute_la_periode"] == 1
    assert r["disponibilite"] == pytest.approx(100 * (1 - 384 / 960))
    vide = gi.disponibilite_parc(episodes(), per, set(), J(10), AUJ)
    assert vide["disponibilite"] == 100 and gi.disponibilite_parc(ep, set(), set(), J(10), AUJ)["disponibilite"] is None


def test_disponibilite_et_dates_a_verifier():
    per = {"a", "b"}                                             # 2 sites × 10 jours = 480 h
    ep = episodes(("a", pd.Timestamp("2019-01-01"), J(5), True, "Autre", None),          # clos, date par défaut
                  ("b", pd.Timestamp("2019-01-01"), None, True, "Autre", None))          # en cours, date par défaut
    r = gi.disponibilite_parc(ep, per, set(), J(10), AUJ)
    assert r["ecartes_a_verifier"] == 1 and r["heures_arret"] == 240                      # seul l'arrêt en cours compte
    assert r["disponibilite"] == 50
    r = gi.disponibilite_parc(ep, per, set(), J(10), AUJ, compter_dates_a_verifier=True)
    assert r["ecartes_a_verifier"] == 0 and r["heures_arret"] == 240 + 120
    ancien = episodes(("a", pd.Timestamp("2019-01-01"), J(50), True, "Autre", None))      # clos avant la période
    assert gi.disponibilite_parc(ancien, per, set(), J(10), AUJ)["ecartes_a_verifier"] == 0


def test_controle_de_la_declaration_d_arret():
    assert gi.controler_arret("Site A", H(2), "Vandalisme", AUJ, set()) == []
    assert "futur" in gi.controler_arret("Site A", AUJ + pd.Timedelta(hours=1), "x", AUJ)[0]
    assert "déjà en cours" in gi.controler_arret("Site A", H(2), "x", AUJ, {"sitea"})[0]
    assert "cause" in gi.controler_arret("Site A", H(2), " ", AUJ)[0]
    assert len(gi.controler_arret(None, None, None, AUJ)) == 3


def test_controle_de_la_remise_en_marche():
    assert gi.controler_remise(H(10), H(2), AUJ) == []
    assert gi.controler_remise(None, H(2), AUJ) == []                                    # début inconnu : pas de comparaison
    assert "précède" in gi.controler_remise(H(2), H(10), AUJ)[0]
    assert "futur" in gi.controler_remise(H(10), AUJ + pd.Timedelta(minutes=5), AUJ)[0]
    assert "Renseigne" in gi.controler_remise(H(10), None, AUJ)[0]


def test_arrets_en_cours_et_duree_mediane():
    ep = episodes(("a", J(4), J(2), False, "x", None), ("b", J(10), J(4), False, "x", None),      # 2 j et 6 j
                  ("c", pd.Timestamp("2019-01-01"), J(1), True, "x", None),                        # date à vérifier : écarté
                  ("d", J(3), None, False, "x", None), ("e", pd.NaT, None, True, "x", None))
    enc = gi.arrets_en_cours(ep, AUJ)
    assert list(enc["cle_site"]) == ["e", "d"] and pd.isna(enc["duree_j"].iloc[0]) and enc["duree_j"].iloc[1] == 3
    assert gi.duree_mediane_arrets(ep) == {"mediane_j": 4.0, "retenus": 2, "ecartes": 1}
    assert gi.duree_mediane_arrets(episodes())["mediane_j"] is None


def test_series_d_arrets():
    occ = pd.DataFrame({"cle_site": ["a", "a", "c", "c", "a"],
                        "date": pd.to_datetime(["2026-03-02", "2026-03-20", "2026-03-05", "2025-07-01", "2026-11-10"])})
    m = gi.arrets_par_mois(occ, 2026).set_index("Mois")
    assert len(m) == 12 and (m.at["Mar", "Arrêts"], m.at["Mar", "Sites distincts"]) == (3, 2) and m.at["Jan", "Arrêts"] == 0
    a = gi.arrets_par_an(occ).set_index("Année")
    assert (a.at[2026, "Arrêts"], a.at[2026, "Sites distincts"], a.at[2025, "Arrêts"]) == (4, 2, 1)
    t = gi.matrice_arrets(occ, PARC, 2026).set_index("Site")
    assert list(t.index) == ["A", "C"] and (t.at["A", "Total 2026"], t.at["A", "Mar 26"], t.at["A", "Nov 26"]) == (3, 2, 1)
    assert (t.at["C", "Total 2025"], t.at["C", "Total 2026"]) == (1, 1) and t.at["A", "Total 2025"] == 0
    assert gi.matrice_arrets(occ[occ["cle_site"] == "zzz"], PARC, 2026).empty and gi.arrets_par_an(occ.iloc[0:0]).empty


def test_causes_et_duree_par_equipe():
    ep = episodes(("a", J(4), J(2), False, "Vandalisme", "Équipe B"), ("b", J(3), None, False, "Vandalisme", "Équipe B "),
                  ("c", J(5), J(4), False, None, "Équipe K"), ("d", pd.NaT, None, True, " ", "Équipe K"),
                  ("e", J(9), J(1), False, "Météo", None))
    c = gi.causes_arrets(ep).set_index("Cause")["Arrêts"]
    assert c["Vandalisme"] == 2 and c["Non précisée"] == 2 and c["Météo"] == 1
    d = gi.duree_arret_par_equipe(ep, AUJ).set_index("Équipe")
    assert list(d.index) == ["Équipe B", "Équipe K"]                         # sans équipe ou sans début : non attribué
    assert d.at["Équipe B", "Jours d'arrêt"] == 5 and d.at["Équipe B", "Arrêts"] == 2 and d.at["Équipe K", "Jours d'arrêt"] == 1


# ============================================================================= lot 4 : visites et équipes
def visites(*lignes):
    """(cle_site, date, chef, type, équipe)"""
    return pd.DataFrame([{"cle_site": k, "site": k.upper(), "date": d, "chef": c, "membres": None, "equipe": e, "type": t,
                          "etat_constate": None, "observations": None, "source": "x"} for k, d, c, t, e in lignes],
                        columns=["cle_site", "site", "date", "chef", "membres", "equipe", "type", "etat_constate", "observations", "source"])


def test_cle_de_nom_et_variantes():
    assert gi.cle_nom("TIAM  TIAGHOUE Valery") == gi.cle_nom(" Tiam Tiaghoue Valéry ") == "tiam tiaghoue valery"
    assert gi.cle_nom("Ngangdi Nelson") != gi.cle_nom("Ngangndi Nelson") and gi.cle_nom(None) == ""
    noms = ["TIAM TIAGHOUE Valery", "TIAM TIAGHOUE VALERY", "Mba Bertrand", "MBA BERTRAND ", "Ahoudja Boris", None, "nan"]
    assert gi.variantes_de_noms(noms) == [["MBA BERTRAND", "Mba Bertrand"], ["TIAM TIAGHOUE VALERY", "TIAM TIAGHOUE Valery"]]
    # une variante déjà validée n'est plus proposée
    assert gi.variantes_de_noms(noms, {"mba bertrand": "MBA Bertrand"}) == [["TIAM TIAGHOUE VALERY", "TIAM TIAGHOUE Valery"]]


def test_rien_n_est_fusionne_sans_validation():
    assert gi.nom_retenu("MBA  BERTRAND") == "MBA BERTRAND" and gi.nom_retenu("Mba Bertrand") == "Mba Bertrand"
    table = {"mba bertrand": "MBA Bertrand", "ngangndi nelson": "Ngangdi Nelson"}
    assert gi.nom_retenu("MBA  BERTRAND", table) == gi.nom_retenu("mba bertrand", table) == "MBA Bertrand"
    assert gi.nom_retenu("Ngangndi Nelson", table) == "Ngangdi Nelson" and gi.nom_retenu("Autre", table) == "Autre"
    assert gi.nom_retenu(" ", table) is None and gi.nom_retenu(None) is None


def test_decoupage_des_intervenants():
    assert gi.decouper_intervenants("ATEBA JOSEPH , HANDSON ANYERE, NSOSEKA EMMANUEL ") == ("ATEBA JOSEPH", "HANDSON ANYERE, NSOSEKA EMMANUEL")
    assert gi.decouper_intervenants("Seul") == ("Seul", None) and gi.decouper_intervenants(None) == (None, None)
    assert gi.liste_membres("A ,B;  C ") == ["A", "B", "C"] and gi.liste_membres(None) == []


def test_controle_d_une_visite():
    assert gi.controler_visite("A", J(1), "Chef", "Inspection", AUJ) == []
    assert "futur" in gi.controler_visite("A", AUJ + pd.Timedelta(days=1), "Chef", "Inspection", AUJ)[0]
    assert "chef" in gi.controler_visite("A", J(1), " ", "Inspection", AUJ)[0]
    assert len(gi.controler_visite(None, None, None, "Autre", AUJ)) == 4


def test_couverture_des_visites():
    v = visites(("a", pd.Timestamp("2026-03-02"), "Chef 1", "Inspection", None), ("a", pd.Timestamp("2026-05-02"), "Chef 1", "Maintenance corrective", None),
                ("b", pd.Timestamp("2026-03-09"), None, "Urgence", None), ("p", pd.Timestamp("2026-03-09"), "Chef 2", "Maintenance préventive", None),
                ("c", pd.Timestamp("2025-03-09"), "Chef 2", "Maintenance corrective", None))
    per = {"a", "b", "c", "d"}
    k = gi.couverture_visites(v, per)
    assert (k["visites"], k["centrales"], k["centrales_perimetre"], k["couverture"], k["jamais"]) == (5, 4, 3, 75, 1)
    assert (k["chefs"], k["sans_chef"]) == (2, 1) and (k["preventives"], k["correctives"], k["urgences"]) == (2, 2, 1)
    mars = gi.filtrer_visites(v, 2026, 3)
    k = gi.couverture_visites(mars, per)
    assert len(mars) == 3 and k["couverture"] == 50 and k["jamais"] == 2
    assert len(gi.filtrer_visites(v, 2026, None, {"a"})) == 2 and gi.couverture_visites(v, set())["couverture"] is None


def test_visites_par_chef_et_par_mois():
    v = visites(("a", pd.Timestamp("2026-03-02"), "Chef 1", "Inspection", None), ("b", pd.Timestamp("2026-03-12"), "Chef 1", "Inspection", None),
                ("a", pd.Timestamp("2026-04-02"), "Chef 1", "Inspection", None), ("c", pd.Timestamp("2026-04-05"), None, "Urgence", None))
    t = gi.visites_par_chef(v).set_index("Chef d'équipe")
    assert (t.at["Chef 1", "Visites"], t.at["Chef 1", "Sites distincts"]) == (3, 2) and t.at["Chef 1", "Dernière visite"] == pd.Timestamp("2026-04-02")
    assert t.at[gi.SANS_CHEF, "Visites"] == 1                                          # les visites sans chef restent visibles
    m = gi.visites_par_mois(v)
    assert list(m["Visites"]) == [2, 2] and list(m["Sites distincts"]) == [2, 2]


EQUIPE_OK = {"nom": "Équipe A", "zone": "ZONE1", "chef": "Chef 1", "telephone": "6 77 00 00 00", "statut": "Active", "membres": "M1, M2"}


def test_controle_d_une_equipe():
    assert gi.controler_equipe(EQUIPE_OK) == []
    assert "déjà" in gi.controler_equipe(EQUIPE_OK, {"équipe  a"})[0]
    assert "téléphone" in gi.controler_equipe(EQUIPE_OK | {"telephone": "12"})[0]
    assert gi.controler_equipe(EQUIPE_OK | {"telephone": None}) == []
    assert len(gi.controler_equipe({"nom": "", "zone": None, "chef": " ", "statut": "?"})) == 4


def _bi_missions():
    return pd.DataFrame({"id": ["BI-1", "BI-2", "BI-3", "BI-4", "BI-5", "BI-6"], "equipe": ["Équipe A"] * 4 + ["Autre", "Équipe A"],
                         "date_prevue": [J(-5), J(3), J(10), J(40), J(3), None], "site": ["A"] * 6, "type": ["Préventive"] * 6,
                         "description": ["x"] * 6, "statut": ["Planifié", "Planifié", "Clôturé", "Terminé", "Planifié", "Planifié"],
                         "date_fin": [None, None, J(9), J(39), None, None]})


def test_missions_et_taux_de_realisation():
    m = gi.missions_depuis_bi(_bi_missions(), {"Équipe A"}, ["Planifié"], AUJ).set_index("id")
    assert list(m.index) == ["BI-1", "BI-2", "BI-3", "BI-4"]                           # autre équipe et sans date : écartés
    assert list(m["statut"]) == ["À venir", "En retard", "Réalisée", "Réalisée"]
    auj_meme = gi.missions_depuis_bi(_bi_missions().assign(date_prevue=AUJ), {"Équipe A"}, [], AUJ)
    assert set(auj_meme.loc[auj_meme["statut_bi"] == "Planifié", "statut"]) == {"À venir"}   # prévue aujourd'hui : pas en retard
    t = gi.taux_realisation(m.reset_index(), AUJ, 30)
    assert t == {"echues": 2, "realisees": 1, "taux": 50.0}                             # BI-2 et BI-3 ; BI-4 hors fenêtre
    assert gi.taux_realisation(m.reset_index().iloc[0:0], AUJ)["taux"] is None
    assert gi.missions_depuis_bi(_bi_missions(), set(), [], AUJ).empty


def test_indicateurs_et_tableau_des_equipes():
    eq = pd.DataFrame([EQUIPE_OK, EQUIPE_OK | {"nom": "Équipe B", "zone": "ZONE9", "chef": "Chef 2", "membres": "M2, Chef 1"},
                       EQUIPE_OK | {"nom": "Équipe C", "statut": "Inactive", "chef": "Chef 3", "membres": None}], columns=gi.COLONNES_EQUIPES)
    m = gi.missions_depuis_bi(_bi_missions(), set(eq["nom"]), ["Planifié"], AUJ)
    k = gi.indicateurs_equipes(eq, m, {"ZONE1", "ZONE2"}, AUJ)
    assert (k["actives"], k["inactives"], k["personnes"]) == (2, 1, 4)                  # Chef 1, Chef 2, M1, M2 sans doublon
    assert (k["zones_couvertes"], k["zones"], k["a_venir"], k["en_retard"], k["realisation_taux"]) == (1, 2, 1, 1, 50)
    v = visites(("a", J(10), "CHEF 1", "Inspection", None), ("b", J(20), "Autre", "Inspection", "Équipe A"),
                ("a", J(500), "Chef 1", "Inspection", None), ("c", J(5), "Chef 2", "Inspection", None))
    parc = PARC.assign(responsable=["Chef 1", "chef 1", "Chef 2", None, None, None])
    t = gi.tableau_equipes(eq, v, m, parc, {"Équipe A": 7}, AUJ).set_index("Équipe")
    assert (t.at["Équipe A", "Interventions 12 mois"], t.at["Équipe A", "Sites visités"], t.at["Équipe A", "Sites affectés"]) == (2, 2, 2)
    assert (t.at["Équipe A", "Missions à venir"], t.at["Équipe A", "Missions en retard"], t.at["Équipe A", "Missions réalisées"]) == (1, 1, 2)
    assert t.at["Équipe A", "Fiches saisies"] == 7 and t.at["Équipe A", "Dernière activité"] == J(9)
    assert t.at["Équipe B", "Interventions 12 mois"] == 1 and t.at["Équipe C", "Membres"] == 0 and pd.isna(t.at["Équipe C", "Dernière activité"])


def test_chefs_sans_equipe():
    eq = pd.DataFrame([EQUIPE_OK], columns=gi.COLONNES_EQUIPES)
    v = visites(("a", J(10), "Chef 1", "Inspection", None), ("b", J(20), "m1", "Inspection", None), ("c", J(30), "Ateba", "Inspection", None),
                ("d", J(5), "Ateba", "Inspection", None), ("e", J(6), "Ateba", "Inspection", None), ("a", J(7), None, "Inspection", None))
    o = gi.chefs_sans_equipe(v, eq, {"c": "ZONE3", "d": "ZONE3", "e": "ZONE1"})
    assert list(o["Chef"]) == ["Ateba"] and o["Visites"].iloc[0] == 3 and o["Zone principale"].iloc[0] == "ZONE3" and o["Dernière"].iloc[0] == J(5)
    assert gi.chefs_sans_equipe(v.iloc[0:1], eq).empty and gi.chefs_sans_equipe(v.iloc[0:0], eq).empty
