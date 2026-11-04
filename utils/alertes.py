"""
Moteur d'alertes — règles déterministes sur les registres de l'application.

Chaque alerte : {"Gravité", "Domaine", "Objet", "Constat", "Action recommandée"}.
Aucune alerte n'est inventée : elle découle d'une valeur présente dans un registre
ou dans le classeur source.
"""
from __future__ import annotations

import smtplib
from email.mime.text import MIMEText

import pandas as pd
import streamlit as st

from . import projets as PJ
from . import revolving as RV
from . import vehicules as VH
from .auth import peut_voir_paie
from .storage import charger

GRAVITES = ["Critique", "Élevée", "Moyenne", "Information"]


def _a(grav, dom, obj, constat, action):
    return {"Gravité": grav, "Domaine": dom, "Objet": obj, "Constat": constat, "Action recommandée": action}


def calculer_alertes(data, seuils: dict) -> pd.DataFrame:
    al = []
    auj = pd.Timestamp.today().normalize()

    # --- Parc automobile
    reg = VH.get_register()
    if reg is not None and not reg.empty:
        for _, r in reg[reg["Statut opérationnel"] == "En panne"].iterrows():
            al.append(_a("Élevée", "Parc automobile", f"{r['ID véhicule']} ({r['N° de plaque']})",
                         "Véhicule déclaré en panne.", "Programmer la réparation ou une réaffectation."))
        ref = VH.with_age_and_reforme(reg, seuils["age_reforme"])
        for _, r in ref[ref["Statut réforme"] == "Échéance dépassée"].iterrows():
            if r["Statut opérationnel"] != "Réformé / sorti du parc":
                al.append(_a("Moyenne", "Parc automobile", f"{r['ID véhicule']} ({r['N° de plaque']})",
                             f"Échéance de réforme dépassée (âge {r['Âge (ans)']:.0f} ans).",
                             "Inscrire le remplacement au prochain budget."))
        j = VH.get_journal()
        vid = j[j["Type d'événement"] == "Vidange"].copy() if j is not None and not j.empty else pd.DataFrame()
        derniere = pd.to_datetime(vid["Date"]).groupby(vid["ID véhicule"]).max() if not vid.empty else pd.Series(dtype="datetime64[ns]")
        for _, r in reg[reg["Statut opérationnel"] == "En service"].iterrows():
            d = derniere.get(r["ID véhicule"])
            if d is not None and not pd.isna(d) and (auj - d).days > seuils["vidange_mois"] * 30:
                al.append(_a("Moyenne", "Parc automobile", f"{r['ID véhicule']} ({r['N° de plaque']})",
                             f"Dernière vidange le {d:%d/%m/%Y} (plus de {seuils['vidange_mois']} mois).",
                             "Programmer la vidange."))

    # --- Suivi de projets
    pj = PJ.get_register()
    if pj is not None and not pj.empty:
        pj = PJ.with_derived_columns(pj)
        bloq = pj[pj["Statut"].isin(PJ.STATUTS_A_RELANCER)]
        for _, r in bloq.iterrows():
            jours = r.get("Jours depuis dernier mouvement")
            if pd.notna(jours) and jours > seuils["projet_jours"]:
                prio = r.get("Région prioritaire (NOSO / Extrême-Nord)") == "Oui"
                al.append(_a("Critique" if prio else "Élevée", "Projets", f"{r['N° projet']} — {r['Site']}",
                             f"{r['Statut']} depuis {int(jours)} jours ({r.get('Motif de blocage') or 'motif non renseigné'})"
                             + (" — région prioritaire." if prio else "."),
                             "Désigner un responsable et fixer une date de relance."))

    # --- Fonds revolving
    rv = RV.get_register()
    if rv is not None and not rv.empty:
        for _, r in rv[rv["Statut"].isin(["En retard", "Litige"])].iterrows():
            al.append(_a("Élevée" if r["Statut"] == "Litige" else "Moyenne", "Fonds revolving",
                         f"{r['N° dossier']} — {r['Localité / site']}", f"Dossier « {r['Statut']} ».",
                         "Relancer le ménage via l'agent en charge."))

    # --- RH terrain (classeur)
    g = getattr(data, "grid", None)
    if g is not None and not g.empty and "Statut équipe" in g.columns:
        n_crit = int((g["Statut équipe"] == "Critique").sum())
        n_part = int((g["Statut équipe"] == "Partielle").sum())
        if n_crit:
            al.append(_a("Critique", "RH terrain", f"{n_crit} équipe(s)", "Équipes en statut critique.",
                         "Recrutement ou redéploiement prioritaire (page Organigramme)."))
        if n_part:
            al.append(_a("Moyenne", "RH terrain", f"{n_part} équipe(s)", "Équipes incomplètes.",
                         "Voir le plan d'action prioritaire (Accueil)."))

    # --- Paie / recrutement (profils habilités uniquement)
    if peut_voir_paie():
        pr = charger("paie_registre")
        if pr is not None and not pr.empty:
            dur = pd.to_numeric(pr.get("Intérim — durée (mois)"), errors="coerce").fillna(0)
            for _, r in pr[dur > 6].iterrows():
                al.append(_a("Moyenne", "Paie", f"{r['Matricule']} — {r['Nom']}", "Intérim de plus de 6 mois (art. 15).",
                             "Régulariser par une nomination ou mettre fin à l'intérim."))
            n_inc = int(pr["Catégorie"].isna().sum())
            if n_inc:
                al.append(_a("Information", "Paie", f"{n_inc} agent(s)", "Catégorie non renseignée : agents hors calcul.",
                             "Compléter le registre de paie."))
        rp = charger("recr_profils")
        if rp is not None and not rp.empty:
            from .paie import duree_essai_statutaire
            for _, r in rp.iterrows():
                try:
                    d = r["Durée d'essai (mois)"]
                    d = duree_essai_statutaire(int(r["Catégorie"]), str(r["Statut"])) if pd.isna(d) else float(d)
                    d = d * 2 if str(r.get("Essai renouvelé")) == "Oui" else d
                    fin = pd.Timestamp(r["Date d'embauche"]) + pd.DateOffset(days=int(round(d * 30)))
                except Exception:  # noqa: BLE001
                    continue
                if auj <= fin <= auj + pd.Timedelta(days=seuils["essai_jours"]):
                    al.append(_a("Élevée", "Recrutement", f"{r['Profil / poste']} × {r['Nombre']}",
                                 f"Fin de période d'essai le {fin:%d/%m/%Y}.",
                                 "Préparer l'évaluation de fin d'essai et la confirmation (ajout des indemnités)."))

    # --- Supervision des centrales
    sup = charger("supervision_mesures")
    if sup is not None and not sup.empty:
        sup["Date"] = pd.to_datetime(sup["Date"])
        ref = sup["Date"].max()
        der = sup.groupby("Centrale")["Date"].max()
        for c, d in der.items():
            if (ref - d).days > seuils["silence_jours"]:
                al.append(_a("Critique", "Centrales", c, f"Aucune donnée depuis le {d:%d/%m/%Y}.",
                             "Vérifier le SmartLogger, la SIM et le crédit de communication ; dépêcher l'équipe."))

    # --- Budget
    from .plaidoyer import budget_registre
    bu = budget_registre()
    if bu is not None and not bu.empty and auj.month >= 7:
        b = bu.copy()
        for c in ("Montant prévu (FCFA)", "Engagé (FCFA)"):
            b[c] = pd.to_numeric(b[c], errors="coerce").fillna(0)
        act = b[b["Exercice"].astype(str) == str(auj.year)].groupby("Activité")[["Montant prévu (FCFA)", "Engagé (FCFA)"]].sum()
        for a, r in act[(act["Montant prévu (FCFA)"] > 0) & (act["Engagé (FCFA)"] == 0)].iterrows():
            al.append(_a("Moyenne", "Budget", a, "Aucun engagement au second semestre.",
                         "Lancer les procédures de passation ou justifier le report."))

    # --- Fraîcheur des données sources
    gen = getattr(data, "generated_on", "") or ""
    import re
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", gen)
    if m:
        d = pd.Timestamp(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if (auj - d).days > seuils["fraicheur_jours"]:
            al.append(_a("Information", "Données", "Classeur source", f"Classeur généré le {d:%d/%m/%Y}.",
                         "Charger une version à jour avant tout rapport officiel."))

    df = pd.DataFrame(al, columns=["Gravité", "Domaine", "Objet", "Constat", "Action recommandée"])
    if not df.empty:
        df["_o"] = df["Gravité"].map({g: i for i, g in enumerate(GRAVITES)})
        df = df.sort_values(["_o", "Domaine"]).drop(columns="_o").reset_index(drop=True)
    return df


def smtp_configure() -> bool:
    try:
        return bool(st.secrets["smtp"]["host"])
    except Exception:  # noqa: BLE001
        return False


def envoyer_recapitulatif(alertes: pd.DataFrame, destinataires: list[str]) -> str:
    """Envoie le récapitulatif par courriel via le serveur SMTP déclaré dans les secrets :
        [smtp] host, port (587), user, password, expediteur"""
    cfg = st.secrets["smtp"]
    lignes = [f"[{r['Gravité']}] {r['Domaine']} — {r['Objet']} : {r['Constat']} → {r['Action recommandée']}"
              for _, r in alertes.iterrows()]
    corps = ("Récapitulatif des alertes — Tableau de bord AER\n\n" + "\n".join(lignes)
             + "\n\nMessage automatique. Détail dans l'application, page Alertes.")
    msg = MIMEText(corps, "plain", "utf-8")
    msg["Subject"] = f"AER — {len(alertes)} alerte(s) au {pd.Timestamp.today():%d/%m/%Y}"
    msg["From"] = cfg.get("expediteur", cfg.get("user"))
    msg["To"] = ", ".join(destinataires)
    with smtplib.SMTP(cfg["host"], int(cfg.get("port", 587)), timeout=20) as s:
        s.starttls()
        if cfg.get("user"):
            s.login(cfg["user"], cfg["password"])
        s.send_message(msg)
    return f"Récapitulatif envoyé à {len(destinataires)} destinataire(s)."
