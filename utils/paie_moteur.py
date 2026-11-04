"""Moteur de calcul de paie AER — mêmes règles que le classeur Calcul_Salaires_AER.xlsx.

Usage :
    from paie_aer import Agent, calculer_paie, calculer_rupture, charger_parametres
    P = charger_parametres("parametres_paie_aer.json")
    r = calculer_paie(Agent(categorie=10, echelon="C", poste="P2", enfants=2), P)
    print(r["net_a_payer"])
"""
from __future__ import annotations
import json
from dataclasses import dataclass, asdict, field


def charger_parametres(chemin: str) -> dict:
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


@dataclass
class Agent:
    categorie: int
    echelon: str
    matricule: str = ""
    nom: str = ""
    statut: str = "Recruté AER"
    poste: str = "Aucun"            # Aucun / P1 / P2 / P3
    interim_palier: str = "Aucun"
    interim_duree_mois: float = 0
    cabinet: str = "Non"            # astreinte (cabinets PCA/DG/DGA)
    enfants: int = 0
    situation: str = "Normal"
    jours_non_payes: float = 0
    mois_presence: float = 12
    treizieme_ce_mois: str = "Non"
    installation_ce_mois: str = "Non"
    medaille: str = "Aucune"        # Aucune / Argent / Vermeil / Or
    gratification: float = 0
    autres_gains_imposables: float = 0
    autres_gains_non_imposables: float = 0
    avance_retenue: float = 0
    autres_retenues: float = 0
    en_essai: str = "Non"           # Oui = période d'essai : seul le salaire de base est versé


def _groupe(cat: int) -> int:
    return 1 if cat <= 6 else (2 if cat <= 9 else 3)


def _mode(calc: float, palier_montant: float, mode: str) -> float:
    if mode == "Plafond":
        return min(calc, palier_montant)
    if mode == "Plus favorable":
        return max(calc, palier_montant)
    return palier_montant  # Forfait palier


def _bareme_paliers(valeur: float, table: list) -> float:
    montant = 0
    for borne, m in table:
        if valeur >= borne:
            montant = m
    return montant


def _irpp_annuel(base: float, R: dict) -> float:
    b1, b2, b3 = R["irpp_bornes"]
    t1, t2, t3, t4 = R["irpp_taux"]
    return (t1 * min(base, b1) + t2 * max(0, min(base, b2) - b1)
            + t3 * max(0, min(base, b3) - b2) + t4 * max(0, base - b3))


def calculer_paie(a: Agent, P: dict) -> dict:
    G, PP, D, O = P["PAR_GROUPE"], P["PAR_PALIER"], P["DIVERS"], P["OPTIONS"]
    R, PAT = P["RETENUES"], P["PATRONAL"]
    g = _groupe(a.categorie) - 1
    base = P["GRILLE"][str(a.categorie)][P["ECHELONS"].index(a.echelon)]

    # Palier effectif (intérim) [Art. 15]
    own = P["PALIERS"].index(a.poste)
    inter = P["PALIERS"].index(a.interim_palier)
    w = inter if (inter > own and a.interim_duree_mois > O["duree_interim_min"]) else own

    def pal(cle):
        return PP[cle][w - 1] if w > 0 else 0

    logement = base * G["logement_taux"][g]
    deplacement = G["deplacement"][g]
    technicite = G["technicite"][g]
    af = G["af_forfait"][g]
    enfants_sup = D["supplement_enfant"] * a.enfants
    if w > 0:
        logement = _mode(logement, pal("logement"), O["mode_logement"])
        deplacement = _mode(deplacement, pal("deplacement"), O["mode_deplacement"])
        technicite = _mode(technicite, pal("technicite"), O["mode_technicite"])
        af = _mode(af, pal("af"), O["mode_af"])
        if O["supplement_enfant_responsables"] != "Oui":
            enfants_sup = 0
    af += enfants_sup

    elements = [
        base, logement, deplacement, technicite, pal("sujetion"), pal("representation"), af,
        pal("fonction"), D["astreinte"] if a.cabinet == "Oui" else 0,
        pal("carburant") if O["carburant_en_paie"] == "Oui" else 0,
        pal("communication") if O["communication_en_paie"] == "Oui" else 0,
    ]
    if a.en_essai == "Oui":
        # Période d'essai : salaire de base seul, indemnités et primes ajoutées après l'essai
        elements = [base] + [0] * (len(elements) - 1)

    st = P["STATUTS"][a.statut]
    taux_sit = P["SITUATIONS"][a.situation][st["detache"]]
    coef = taux_sit * max(0, O["diviseur_journalier"] - a.jours_non_payes) / O["diviseur_journalier"]
    recurrents = [e * coef for e in elements]

    base13 = base if O["base_13e_mois"] == "Salaire de base" else sum(elements)
    treizieme = (base13 * a.mois_presence / 12
                 if a.treizieme_ce_mois == "Oui" and a.mois_presence >= O["presence_min_13e"] else 0)
    installation = D["prime_installation"] if a.installation_ce_mois == "Oui" else 0
    medaille = {"Aucune": 0, "Argent": D["medaille_argent"], "Vermeil": D["medaille_vermeil"],
                "Or": D["medaille_or"]}[a.medaille]
    occ = [treizieme, installation, medaille, a.gratification]

    brut = sum(recurrents) + sum(occ) + a.autres_gains_imposables + a.autres_gains_non_imposables
    brut_cnps = (sum(v * f for v, f in zip(recurrents, P["SOUMIS_CNPS"]))
                 + sum(v * f for v, f in zip(occ, P["OCC_CNPS"])) + a.autres_gains_imposables)
    brut_imp = (sum(v * f for v, f in zip(recurrents, P["SOUMIS_IRPP"]))
                + sum(v * f for v, f in zip(occ, P["OCC_IRPP"])) + a.autres_gains_imposables)

    assiette_cnps = min(brut_cnps, R["cnps_plafond"]) * st["cnps"]
    cnps = R["cnps_sal"] * assiette_cnps
    cfc = R["cfc_sal"] * brut_imp
    if brut_imp < R["seuil_irpp"]:
        irpp = 0
    else:
        ni_annuel = max(0, 12 * (brut_imp * (1 - R["abattement_frais_pro"]) - cnps) - R["abattement_annuel"])
        irpp = _irpp_annuel(ni_annuel, R) / 12
    cac = R["cac"] * irpp
    rav = _bareme_paliers(brut_imp, P["RAV"])
    tdl = _bareme_paliers(base, P["TDL"]) if coef > 0 else 0  # pas de TDL si aucun salaire versé
    retenues = cnps + cfc + irpp + cac + rav + tdl + a.avance_retenue + a.autres_retenues

    pat = {k: PAT[k] * assiette_cnps for k in ("pvid", "af", "at")}
    pat["cfc_pat"] = PAT["cfc_pat"] * brut_imp
    pat["fne"] = PAT["fne"] * brut_imp
    charges = sum(pat.values())

    noms = ["salaire_base", "ind_logement", "ind_deplacement", "prime_technicite", "prime_sujetion",
            "prime_representation", "allocation_familiale", "prime_fonction", "prime_astreinte",
            "dotation_carburant", "credit_communication"]
    out = {"groupe": g + 1, "palier_effectif": P["PALIERS"][w], "coefficient_maintien": coef}
    out.update({n: v for n, v in zip(noms, elements)})
    out.update({
        "total_recurrent_proratise": sum(recurrents), "treizieme_mois": treizieme,
        "prime_installation": installation, "medaille": medaille, "gratification": a.gratification,
        "brut_total": brut, "brut_soumis_cnps": brut_cnps, "brut_imposable": brut_imp,
        "cnps_salarie": cnps, "cfc_salarie": cfc, "irpp": irpp, "cac": cac, "rav": rav, "tdl": tdl,
        "avance_retenue": a.avance_retenue, "autres_retenues": a.autres_retenues,
        "total_retenues": retenues, "net_a_payer": brut - retenues,
        **{f"patronal_{k}": v for k, v in pat.items()},
        "total_charges_patronales": charges, "cout_employeur": brut + charges,
    })
    return out


def indemnite_licenciement(salaire_moyen: float, annees: float, P: dict) -> float:
    b, t = P["LICENCIEMENT"]["bornes"], P["LICENCIEMENT"]["taux"]
    coef = (t[0] * min(annees, b[0]) + t[1] * max(0, min(annees, b[1]) - b[0])
            + t[2] * max(0, min(annees, b[2]) - b[1]) + t[3] * max(0, min(annees, b[3]) - b[2])
            + t[4] * max(0, annees - b[3]))
    return salaire_moyen * coef


def calculer_rupture(motif: str, categorie: int, echelon: str, anciennete: float, salaire_moyen: float,
                     mois_depuis_dernier_conge: float, jours_travailles_mois: float,
                     preavis_execute: str, P: dict) -> dict:
    """motif : Licenciement | Licenciement économique | Licenciement pour faute lourde | Démission | Décès | Retraite"""
    RU, O = P["RUPTURE"], P["OPTIONS"]
    g = _groupe(categorie)
    col = 0 if anciennete < 1 else (1 if anciennete <= 5 else 2)
    preavis_mois = P["PREAVIS"][str(g)][col]
    base = P["GRILLE"][str(categorie)][P["ECHELONS"].index(echelon)]
    ind_brute = indemnite_licenciement(salaire_moyen, anciennete, P)
    # condition d'ancienneté minimale appliquée au seul licenciement (pas au décès ni à la retraite)
    ind_lic = ind_brute if anciennete >= RU["anciennete_min_licenciement"] else 0
    jours_conge = RU["jours_conge_par_mois"] * mois_depuis_dernier_conge
    ind_conge = salaire_moyen / O["diviseur_journalier"] * jours_conge
    reliquat = salaire_moyen / O["diviseur_journalier"] * jours_travailles_mois
    r = {"preavis_mois": preavis_mois, "indemnite_preavis": 0, "indemnite_licenciement": 0,
         "indemnite_deces": 0, "indemnite_fin_carriere": 0, "prime_bonne_separation": 0,
         "indemnite_conge": ind_conge, "reliquat_salaire": reliquat}
    if motif in ("Licenciement", "Licenciement économique"):
        r["indemnite_licenciement"] = ind_lic
        if preavis_execute != "Oui":
            r["indemnite_preavis"] = preavis_mois * salaire_moyen
    elif motif == "Démission":
        if preavis_execute != "Oui":  # due PAR l'agent
            r["indemnite_preavis"] = -preavis_mois * salaire_moyen
    elif motif == "Décès":
        r["indemnite_deces"] = RU["mult_deces"] * ind_brute
    elif motif == "Retraite":
        r["indemnite_fin_carriere"] = RU["mult_retraite"] * ind_brute
        r["prime_bonne_separation"] = RU["bonne_separation"] * 12 * base * anciennete
    r["total"] = sum(v for k, v in r.items() if k != "preavis_mois")
    return r


if __name__ == "__main__":
    import sys
    P = charger_parametres(sys.argv[1] if len(sys.argv) > 1 else "parametres_paie_aer.json")
    print(json.dumps(calculer_paie(Agent(categorie=10, echelon="C", poste="P2", enfants=2), P), indent=2))
