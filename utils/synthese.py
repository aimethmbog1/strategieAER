"""Synthèse transversale : un bloc d'indicateurs par domaine de l'application, calculé à partir des registres
enregistrés en base et du classeur source. Un domaine sans données ou en erreur n'empêche jamais l'affichage
des autres (son bloc l'indique)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .storage import charger

RACINE = Path(__file__).resolve().parent.parent
MOIS_ABR = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def nb(x, d=0) -> str:
    """Nombre au format français : espace pour les milliers, virgule décimale."""
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    return f"{x:,.{d}f}".replace(",", " ").replace(".", ",")


def fcfa(x) -> str:
    if x is None or pd.isna(x):
        return "—"
    if abs(x) >= 1e9:
        return f"{nb(x / 1e9, 2)} Md FCFA"
    if abs(x) >= 1e6:
        return f"{nb(x / 1e6, 1)} M FCFA"
    return f"{nb(x)} FCFA"


def pct(x, d=1) -> str:
    return "—" if x is None or pd.isna(x) else f"{nb(x, d)} %"


@dataclass
class Bloc:
    domaine: str
    icone: str
    page: str  # chemin du fichier de page
    kpis: list = field(default_factory=list)  # [(libellé, valeur, précision|None)]
    note: str = ""
    etat: str = "ok"  # ok | vide | erreur


def _page(prefixe: str) -> str:
    for f in sorted((RACINE / "vues").iterdir()):
        if f.name.startswith(prefixe) and f.suffix == ".py":
            return f"vues/{f.name}"
    return ""


def _sur(domaine, icone, prefixe, fn) -> Bloc:
    b = Bloc(domaine, icone, _page(prefixe))
    try:
        fn(b)
    except Exception as e:  # noqa: BLE001 — un domaine défaillant ne bloque pas la synthèse
        b.etat, b.note = "erreur", f"Indicateurs indisponibles ({type(e).__name__})."
    if not b.kpis and b.etat == "ok":
        b.etat = "vide"
    return b


# ----------------------------------------------------------------------------- domaines
def _parc(data):
    def f(b):
        from . import gmao_core as gc
        from . import gmao_ui
        from . import maintenance as mt
        ref = mt.referentiel_sites(data.sites)
        cl = gmao_ui.classes_sites(ref)
        cl = (cl if cl is not None else pd.Series("Non renseigné", index=ref["site_id"]))
        cl = cl[~cl.index.duplicated()].reindex(ref["site_id"]).fillna("Non renseigné")
        bi = gc.table("gmao_bi")
        arr = set(bi.loc[bi["statut"].isin(gc.STATUTS_BI_OUVERTS) & bi["centrale_arret"], "site_id"])
        cl = cl.where(~cl.index.isin(arr), "À l'arrêt")
        p = pd.to_numeric(ref.set_index("site_id")["Puissance (kWc)"], errors="coerce")
        serv = cl.isin(["Fonctionnelle (H24)", "Fonctionnement partiel"])
        b.kpis = [("Centrales", nb(len(ref)), f"{nb(p.sum(), 0)} kWc installés"),
                  ("En service", f"{nb(serv.sum())} / {nb(len(ref))}", pct(100 * serv.mean())),
                  ("À l'arrêt", nb((cl == "À l'arrêt").sum()), None),
                  ("Puissance en service", f"{nb(p[serv.values].sum())} kWc", pct(100 * p[serv.values].sum() / p.sum())),
                  ("État non renseigné", nb((cl == "Non renseigné").sum()), "Phase 3 surtout")]
        b.extra = cl  # réutilisé pour le graphique
    return f


def _gmao():
    def f(b):
        from . import gmao_core as gc
        bi, di = gc.table("gmao_bi"), gc.table("gmao_di")
        k = gc.kpis_bi(bi, pd.Timestamp(gc.maintenant()).normalize())
        b.kpis = [("DI nouvelles", nb((di["statut"] == "Nouvelle").sum()), None),
                  ("BI ouverts", nb(k["ouverts"]), f"{nb(k['en_retard'])} en retard"),
                  ("BI non affectés", nb(k["non_affectes"]), None),
                  ("BI clôturés", nb((bi["statut"] == "Clôturé").sum()), None)]
        dj = charger("gmao_defauts")
        if dj is not None and len(dj):
            b.kpis.append(("Défauts (journaux)", nb(len(dj)), None))
    return f


def _rh(data):
    def f(b):
        from .personnel import MANQUANT, get_effective_roster
        eq, nonaff = get_effective_roster(data.equipes_rows, data.unassigned)
        if eq is None or eq.empty:
            return
        add = eq["Rôle"].astype(str).str.contains("additionnel", case=False)
        req = eq[~add]  # postes requis : 4 par équipe ; les agents « additionnels » sont comptés à part
        pourvus = int((req["Nom"].astype(str).str.strip() != MANQUANT).sum())
        b.kpis = [("Équipes", nb(req.groupby(["Antenne", "Zone"]).ngroups), None),
                  ("Postes pourvus / requis", f"{pourvus} / {len(req)}", pct(100 * pourvus / len(req))),
                  ("Postes vacants", nb(len(req) - pourvus), f"+ {int(add.sum())} agent(s) additionnel(s)" if add.any() else None),
                  ("Agents non affectés", nb(0 if nonaff is None else len(nonaff)), None)]
    return f


def _vehicules():
    def f(b):
        from . import vehicules as VH
        reg = VH.get_register()
        if reg is None or reg.empty:
            return
        ref = VH.with_age_and_reforme(reg, VH.SEUIL_AGE_REFORME_DEFAUT_ANS)
        b.kpis = [("Véhicules", nb(len(reg)), None),
                  ("En panne", nb((reg["Statut opérationnel"] == "En panne").sum()), None),
                  ("Réforme échue", nb((ref["Statut réforme"] == "Échéance dépassée").sum()), None)]
    return f


def _projets():
    def f(b):
        from . import projets as PJ
        reg = PJ.with_derived_columns(PJ.get_register())
        if reg.empty:
            b.note = "Aucun projet saisi."
            return
        st_ = reg["Statut"].astype(str).value_counts()
        b.kpis = [("Projets suivis", nb(len(reg)), None)] + [(s, nb(n), None) for s, n in st_.head(3).items()]
        j = pd.to_numeric(reg["Jours depuis dernier mouvement"], errors="coerce")
        b.kpis.append(("Sans mouvement > 60 j", nb((j > 60).sum()), None))
    return f


def _revolving():
    def f(b):
        from . import revolving as RV
        reg = RV.with_derived_columns(RV.get_register())
        if reg.empty:
            b.note = "Aucun dossier saisi."
            return
        du = pd.to_numeric(reg["Montant à rembourser (FCFA)"], errors="coerce").sum()
        solde = pd.to_numeric(reg["Solde restant dû (FCFA)"], errors="coerce").sum()
        b.kpis = [("Dossiers", nb(len(reg)), None), ("À rembourser", fcfa(du), None),
                  ("Recouvrement", pct(100 * (du - solde) / du) if du else "—", f"solde {fcfa(solde)}")]
    return f


def _budget():
    def f(b):
        reg = charger("budget_register")
        src = ""
        if reg is None or reg.empty:
            seed = RACINE / "data" / "budget_sdmse_2027.csv"
            if not seed.exists():
                return
            reg, src = pd.read_csv(seed), "budget initial 2027 (aucune saisie enregistrée)"
        m = {c: pd.to_numeric(reg[c], errors="coerce").sum() for c in ["Montant prévu (FCFA)", "Engagé (FCFA)", "Payé (FCFA)"] if c in reg}
        pv = m.get("Montant prévu (FCFA)", 0)
        b.kpis = [("Prévu", fcfa(pv), None),
                  ("Engagé", fcfa(m.get("Engagé (FCFA)")), pct(100 * m.get("Engagé (FCFA)", 0) / pv) if pv else None),
                  ("Payé", fcfa(m.get("Payé (FCFA)")), pct(100 * m.get("Payé (FCFA)", 0) / pv) if pv else None)]
        b.note = src
    return f


def _recharges():
    def f(b):
        from .recharges import COLONNES_BASE, enrichir, lire_classeur_recharges, mois_complets
        reg = charger("recharges_datacenter")
        if reg is None or reg.empty:
            fic = RACINE / "data" / "recharges_datacenter.xlsx"
            if not fic.exists():
                return
            reg = lire_classeur_recharges(fic.read_bytes())[COLONNES_BASE]
        d = enrichir(reg)
        an = int(d["annee"].max())
        cur = d[d["annee"] == an]
        rc = cur["recettes"].sum()
        comp = mois_complets(d)  # comparaison à période égale, sur les mois complets uniquement
        cc = comp[comp["annee"] == an]
        mm = int(cc["mois_num"].max()) if len(cc) else 0
        r1 = cc["recettes"].sum()
        rp = comp[(comp["annee"] == an - 1) & (comp["mois_num"] <= mm)]["recettes"].sum()
        evol = f"{'+' if r1 >= rp else ''}{nb(100 * (r1 / rp - 1), 1)} % vs {an - 1} (janv.–{MOIS_ABR[mm - 1]})" if rp and mm else None
        b.kpis = [(f"Recettes {an}", fcfa(rc), evol),
                  (f"Énergie vendue {an}", f"{nb(cur['energie_kwh'].sum())} kWh", None),
                  ("Recettes cumulées (historique)", fcfa(d["recettes"].sum()), f"depuis {d['mois'].min():%m/%Y}")]
        b.extra = d
    return f


def _ventes():
    def f(b):
        v = charger("ventes_register")
        if v is None or v.empty:
            b.note = "Aucun état de vente importé."
            return
        b.kpis = [("Ventes importées", nb(len(v)), None),
                  ("Recettes", fcfa(pd.to_numeric(v.get("Montant (FCFA)"), errors="coerce").sum()), None),
                  ("Énergie", f"{nb(pd.to_numeric(v.get('Énergie (kWh)'), errors='coerce').sum())} kWh", None)]
    return f


def _clients_inst():
    def f(b):
        from . import clients_inst as ci
        op, fac, pay = (charger(n) for n in ("ci_operations", "ci_factures", "ci_paiements"))
        if op is None or op.empty:
            b.note = "Aucune recharge de client institutionnel saisie."
            return
        op, fac, pay = ci._normaliser("ci_operations", op), ci._normaliser("ci_factures", fac), ci._normaliser("ci_paiements", pay)
        fs = ci.factures_avec_soldes(fac, pay, pd.Timestamp(ci.maintenant()).normalize())
        an = int(op["date"].dt.year.max())
        o = op[op["date"].dt.year == an]
        b.kpis = [(f"Ventes {an} (HT)", fcfa(o["montant_ht"].sum()), f"{o['client'].nunique()} client(s)"),
                  ("Énergie rechargée", f"{nb(o.loc[o['type'] == 'Recharge', 'quantite'].sum())} kWh", None),
                  ("Reste à recouvrer", fcfa(fs["reste"].sum()), f"{int(fs['statut'].str.contains('chue', na=False).sum())} facture(s) échue(s)"),
                  ("Non facturé (HT)", fcfa(op.loc[op["facture_id"].isna(), "montant_ht"].sum()), None)]
    return f


def _compteurs():
    def f(b):
        lots = charger("compteurs_lots")
        from .compteurs import get_cached_dataframe
        df = None
        try:
            df = get_cached_dataframe()
        except Exception:  # noqa: BLE001
            pass
        if df is not None and len(df) and "Phase" in df:
            ph = df["Phase"].astype(str).value_counts().sort_index()
            b.kpis = [("Compteurs analysés", nb(len(df)), None)] + [(p, nb(n), None) for p, n in ph.items()]
        elif lots is not None and len(lots):
            b.kpis = [("Lots Holley déposés", nb(len(lots)), "ouvrir la page pour les analyser")]
        else:
            b.note = "Aucun lot de compteurs déposé."
    return f


def _supervision():
    def f(b):
        m = charger("supervision_mesures")
        if m is None or m.empty:
            b.note = "Aucune mesure de supervision importée."
            return
        d = pd.to_datetime(m["Date"], errors="coerce")
        b.kpis = [("Centrales suivies", nb(m["Centrale"].nunique()), None),
                  ("Production enregistrée", f"{nb(pd.to_numeric(m['Production (kWh)'], errors='coerce').sum())} kWh", None),
                  ("Dernière mesure", f"{d.max():%d/%m/%Y}" if d.notna().any() else "—", None)]
    return f


def _alertes(data):
    def f(b):
        from .alertes import GRAVITES, calculer_alertes
        from .parametres import valeur
        s = {"projet_jours": 60, "vidange_mois": 6, "age_reforme": 7, "essai_jours": 30, "silence_jours": 2,
             "fraicheur_jours": 60, **(valeur("alertes", "seuils", {}) or {})}
        al = calculer_alertes(data, s)
        b.kpis = [(g, nb(0 if al.empty else (al["Gravité"] == g).sum()), None) for g in GRAVITES]
        b.extra = al
    return f


def blocs(data) -> list[Bloc]:
    return [
        _sur("Parc solaire en exploitation", "☀️", "2_", _parc(data)),
        _sur("Maintenance (GMAO)", "🔧", "23_", _gmao()),
        _sur("Alertes", "🚨", "19_", _alertes(data)),
        _sur("Recharges Data Center", "🔋", "21_", _recharges()),
        _sur("Recettes et abonnés", "💵", "18_", _ventes()),
        _sur("Clients institutionnels", "🏢", "25_", _clients_inst()),
        _sur("Compteurs", "🔌", "8_", _compteurs()),
        _sur("Supervision des centrales", "📡", "17_", _supervision()),
        _sur("Équipes terrain", "👷", "3_", _rh(data)),
        _sur("Parc automobile", "🚗", "12_", _vehicules()),
        _sur("Suivi budgétaire", "📒", "16_", _budget()),
        _sur("Projets d'électrification", "📌", "9_", _projets()),
        _sur("Fonds revolving", "💰", "7_", _revolving()),
    ]
