"""Clients institutionnels (MTN, IHS…) : recharges, achats de compteurs, factures, paiements et recouvrement.

Registres en base : ci_clients, ci_operations, ci_factures, ci_paiements. Aucun montant n'est deviné : le prix
d'une opération vient de la saisie ou du tarif déclaré dans la fiche du client.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from .storage import mettre_a_jour, session_ou_stockage

TYPES_OP = ["Recharge", "Achat de compteurs", "Autre prestation"]
UNITES = {"Recharge": "kWh", "Achat de compteurs": "compteur(s)", "Autre prestation": "unité(s)"}
MODES_PAIEMENT = ["Virement", "Chèque", "Mobile money", "Espèces", "Compensation", "Autre"]
TVA_DEFAUT = 19.25  # taux normal au Cameroun (TVA 17,5 % + centimes additionnels) — à confirmer pour l'AER

COLS = {
    "ci_clients": ["id", "nom", "raison_sociale", "niu", "adresse", "contact", "email", "delai_paiement_j",
                   "tarif_kwh", "prix_compteur", "actif", "observations"],
    "ci_operations": ["id", "date", "client", "type", "site", "compteur", "quantite", "prix_unitaire", "montant_ht",
                      "reference", "facture_id", "observations"],
    "ci_factures": ["id", "date", "client", "periode_debut", "periode_fin", "objet", "montant_ht", "taux_tva",
                    "montant_tva", "montant_ttc", "echeance", "annulee", "observations"],
    "ci_paiements": ["id", "date", "facture_id", "client", "montant", "mode", "reference", "observations"],
}
DATES = {"date", "periode_debut", "periode_fin", "echeance"}
NUMS = {"delai_paiement_j", "tarif_kwh", "prix_compteur", "quantite", "prix_unitaire", "montant_ht", "taux_tva",
        "montant_tva", "montant_ttc", "montant"}
BOOLS = {"actif", "annulee"}
CLIENTS_INITIAUX = [
    {"id": "MTN", "nom": "MTN Cameroon", "raison_sociale": "MTN Cameroon S.A.", "delai_paiement_j": 30, "actif": True},
    {"id": "IHS", "nom": "IHS Cameroon", "raison_sociale": "IHS Cameroon S.A.", "delai_paiement_j": 30, "actif": True},
]


def maintenant() -> datetime:
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Africa/Douala")).replace(tzinfo=None, second=0, microsecond=0)


def _normaliser(nom, df):
    cols = COLS[nom]
    df = pd.DataFrame(columns=cols) if df is None or len(df) == 0 else df.copy()
    for c in cols:
        if c not in df.columns:
            df[c] = None
    for c in cols:
        if c in DATES:
            x = pd.to_datetime(df[c], errors="coerce")
            df[c] = x.dt.tz_localize(None) if getattr(x.dt, "tz", None) is not None else x
        elif c in NUMS:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        elif c in BOOLS:
            df[c] = df[c].fillna(c == "actif").astype(bool)
    return df[cols].reset_index(drop=True)


def table(nom: str) -> pd.DataFrame:
    defaut = (lambda: pd.DataFrame(CLIENTS_INITIAUX)) if nom == "ci_clients" else (lambda: pd.DataFrame(columns=COLS[nom]))
    return _normaliser(nom, session_ou_stockage(nom, defaut))


def sauver(nom: str, df: pd.DataFrame, detail: str) -> bool:
    return mettre_a_jour(nom, _normaliser(nom, df), detail)


def nouvel_id(df: pd.DataFrame, prefixe: str, an: int | None = None) -> str:
    an = an or maintenant().year
    deja = df["id"].dropna().astype(str)
    nums = pd.to_numeric(deja[deja.str.startswith(f"{prefixe}-{an}-")].str.split("-").str[-1], errors="coerce").dropna()
    return f"{prefixe}-{an}-{int(nums.max()) + 1 if len(nums) else 1:04d}"


def ajouter(nom: str, lignes: list[dict], prefixe: str, detail: str) -> list[str]:
    df = table(nom)
    ids = []
    for l in lignes:
        l = {**l, "id": nouvel_id(df, prefixe)}
        ids.append(l["id"])
        df = pd.concat([df, pd.DataFrame([{c: l.get(c) for c in COLS[nom]}])], ignore_index=True)
    sauver(nom, df, detail)
    return ids


# ----------------------------------------------------------------------------- calculs
def factures_avec_soldes(fac: pd.DataFrame, pay: pd.DataFrame, aujourd_hui: pd.Timestamp) -> pd.DataFrame:
    f = fac.copy()
    paye = pay.groupby("facture_id")["montant"].sum() if len(pay) else pd.Series(dtype=float)
    f["paye"] = pd.to_numeric(f["id"].map(paye.to_dict()), errors="coerce").fillna(0.0)
    f["reste"] = (f["montant_ttc"].fillna(0) - f["paye"]).clip(lower=0)
    f.loc[f["annulee"], "reste"] = 0.0
    def statut(r):
        if r["annulee"]:
            return "Annulée"
        if r["reste"] <= 0.5:
            return "Payée"
        if r["paye"] > 0:
            return "Partiellement payée" + (" — échue" if pd.notna(r["echeance"]) and r["echeance"] < aujourd_hui else "")
        return "Échue" if pd.notna(r["echeance"]) and r["echeance"] < aujourd_hui else "Émise"
    f["statut"] = f.apply(statut, axis=1) if len(f) else pd.Series(dtype=object, index=f.index)
    f["retard_j"] = ((aujourd_hui - f["echeance"]).dt.days).where(f["reste"] > 0.5).clip(lower=0)
    der = pay.groupby("facture_id")["date"].max() if len(pay) else pd.Series(dtype="datetime64[ns]")
    f["date_solde"] = pd.to_datetime(f["id"].map(der.to_dict()), errors="coerce").where(f["statut"] == "Payée")
    f["delai_paiement_j"] = (f["date_solde"] - f["date"]).dt.days
    return f


def anciennete(f: pd.DataFrame) -> pd.DataFrame:
    """Balance âgée du reste à recouvrer, par client."""
    x = f[f["reste"] > 0.5].copy()
    tr = pd.cut(x["retard_j"].fillna(0), [-1, 0, 30, 60, 90, 1e9],
                labels=["Non échu", "1–30 j", "31–60 j", "61–90 j", "> 90 j"])
    x["tranche"] = tr
    return x.pivot_table(index="client", columns="tranche", values="reste", aggfunc="sum", observed=False, fill_value=0)


def synthese_clients(op, f, pay, clients) -> pd.DataFrame:
    noms = dict(zip(clients["id"], clients["nom"]))
    lignes = []
    for cid in sorted(set(clients["id"]) | set(op["client"].dropna()) | set(f["client"].dropna())):
        o = op[op["client"] == cid]
        r = o[o["type"] == "Recharge"]
        c = o[o["type"] == "Achat de compteurs"]
        ff = f[(f["client"] == cid) & ~f["annulee"]]
        lignes.append({
            "Client": noms.get(cid, cid), "code": cid,
            "Recharges": len(r), "Énergie rechargée (kWh)": r["quantite"].sum(),
            "Montant recharges (FCFA HT)": r["montant_ht"].sum(),
            "Compteurs achetés": c["quantite"].sum(), "Montant compteurs (FCFA HT)": c["montant_ht"].sum(),
            "Non facturé (FCFA HT)": o.loc[o["facture_id"].isna() | (o["facture_id"].astype(str) == ""), "montant_ht"].sum(),
            "Facturé (FCFA TTC)": ff["montant_ttc"].sum(), "Encaissé (FCFA)": ff["paye"].sum(),
            "Reste à recouvrer (FCFA)": ff["reste"].sum(),
            "Factures échues": int(ff["statut"].str.contains("chue", na=False).sum()),
            "Délai moyen de paiement (j)": ff["delai_paiement_j"].mean(),
            "Dernière recharge": r["date"].max(),
        })
    s = pd.DataFrame(lignes)
    if len(s):
        s["Taux de recouvrement (%)"] = (100 * s["Encaissé (FCFA)"] / s["Facturé (FCFA TTC)"].where(s["Facturé (FCFA TTC)"] > 0)).round(1)
    return s


# ----------------------------------------------------------------------------- import de fichier
CHAMPS_IMPORT = {"date": r"date|jour", "client": r"client|op[ée]rateur|soci[ée]t[ée]", "type": r"^type|nature|op[ée]ration",
                 "quantite": r"kwh|[ée]nergie|quantit|qt[ée]|nombre", "prix_unitaire": r"prix|tarif|p\.?u",
                 "montant_ht": r"montant|total|valeur", "site": r"site|localit|village",
                 "compteur": r"compteur|meter|n[°o]\s*cpt", "reference": r"r[ée]f|token|bon"}


def _nombre(v) -> float:
    """« 1 250 000 », « 1 250,5 », 1250 → nombre ; sinon NaN."""
    import re
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return float("nan")
    if isinstance(v, (int, float)):
        return float(v)
    t = re.sub(r"[^0-9,.\-]", "", str(v)).replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return float("nan")


def deviner_colonnes(raw: pd.DataFrame) -> dict:
    import re
    return {k: next((c for c in raw.columns if re.search(m, str(c), re.I)), None) for k, m in CHAMPS_IMPORT.items()}


def preparer_import(raw: pd.DataFrame, choix: dict, client_defaut: str, type_defaut: str, noms: dict) -> pd.DataFrame:
    """Ramène un fichier quelconque aux colonnes du registre ; lignes sans date ou sans montant écartées."""
    import re
    x = pd.DataFrame({k: (raw[v] if v else None) for k, v in choix.items()}, index=raw.index)
    x["date"] = pd.to_datetime(x["date"], errors="coerce", dayfirst=True)
    if not choix.get("client"):
        x["client"] = client_defaut
    else:
        idx = {re.sub(r"\W", "", str(nm).lower()): k for k, nm in noms.items()} | {k.lower(): k for k in noms}
        x["client"] = x["client"].astype(str).map(
            lambda s: next((k for kk, k in idx.items() if kk and kk in re.sub(r"\W", "", s.lower())), s.strip()))
    if not choix.get("type"):
        x["type"] = type_defaut
    else:
        x["type"] = x["type"].astype(str).map(lambda s: "Achat de compteurs" if re.search("compteur|meter", s, re.I)
                                              else "Recharge" if re.search("rech|kwh|token|cr[ée]dit", s, re.I)
                                              else "Autre prestation")
    for c in ("quantite", "prix_unitaire", "montant_ht"):
        x[c] = x[c].map(_nombre).astype(float)
    x["montant_ht"] = x["montant_ht"].fillna(x["quantite"] * x["prix_unitaire"])
    for c in ("site", "compteur", "reference"):
        x[c] = x[c].where(x[c].notna(), None).astype(object)
        x.loc[x[c].notna(), c] = x.loc[x[c].notna(), c].astype(str).str.strip()
    return x[x["date"].notna() & (x["montant_ht"].fillna(0) > 0)].reset_index(drop=True)


# ----------------------------------------------------------------------------- montant en lettres
_U = ["zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix", "onze", "douze", "treize",
      "quatorze", "quinze", "seize"]
_D = {2: "vingt", 3: "trente", 4: "quarante", 5: "cinquante", 6: "soixante"}


def _cent(n: int) -> str:
    if n < 17:
        return _U[n]
    if n < 20:
        return "dix-" + _U[n - 10]
    if n < 70:
        d, u = divmod(n, 10)
        return _D[d] + ("" if u == 0 else (" et un" if u == 1 else "-" + _U[u]))
    if n < 80:
        return "soixante" + (" et onze" if n == 71 else "-" + _cent(n - 60))
    if n < 100:
        return "quatre-vingt" + ("s" if n == 80 else "-" + _cent(n - 80))
    c, r = divmod(n, 100)
    tete = "cent" if c == 1 else _U[c] + " cent" + ("s" if r == 0 else "")
    return tete + ("" if r == 0 else " " + _cent(r))


def en_lettres(n: float) -> str:
    n = int(round(n or 0))
    if n == 0:
        return "zéro"
    parts = []
    for valeur, sing, plur in ((10**9, "milliard", "milliards"), (10**6, "million", "millions"), (1000, "mille", "mille")):
        q, n = divmod(n, valeur)
        if q:
            if valeur == 1000:
                parts.append("mille" if q == 1 else _cent(q).replace("cents", "cent").replace("vingts", "vingt") + " mille")
            else:
                parts.append(_cent(q) + " " + (sing if q == 1 else plur))
    if n:
        parts.append(_cent(n))
    return " ".join(parts)


# ----------------------------------------------------------------------------- facture PDF
def facture_pdf(fac: pd.Series, lignes: pd.DataFrame, client: pd.Series | None, emetteur: dict) -> bytes:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    from .rapports import _pdf_safe as S

    def m(x):
        return f"{x:,.0f}".replace(",", " ")

    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(True, 18)
    pdf.add_page()
    pdf.set_fill_color(20, 83, 45)
    pdf.rect(0, 0, 210, 6, "F")
    pdf.set_y(12)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(110, 7, S(emetteur.get("nom") or "Agence d'Électrification Rurale (AER)"), new_x=XPos.RIGHT)
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 7, "FACTURE", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 9)
    for l in (emetteur.get("adresse") or "Yaoundé — Cameroun").split("\n"):
        pdf.cell(110, 5, S(l), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if emetteur.get("niu"):
        pdf.cell(110, 5, S(f"NIU : {emetteur['niu']}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    y = 20
    pdf.set_xy(120, y)
    pdf.set_font("Helvetica", "", 10)
    for k, v in (("N°", fac["id"]), ("Date", f"{fac['date']:%d/%m/%Y}"),
                 ("Échéance", f"{fac['echeance']:%d/%m/%Y}" if pd.notna(fac["echeance"]) else "—"),
                 ("Période", f"{fac['periode_debut']:%d/%m/%Y} au {fac['periode_fin']:%d/%m/%Y}"
                  if pd.notna(fac["periode_debut"]) else "—")):
        pdf.set_x(120)
        pdf.cell(25, 6, S(k), new_x=XPos.RIGHT)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, S(str(v)), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 10)
    pdf.set_y(max(pdf.get_y(), 48) + 4)
    pdf.set_fill_color(240, 253, 244)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 7, S("Facturé à"), fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 10)
    if client is not None:
        for v in (client.get("raison_sociale") or client.get("nom"), client.get("adresse"),
                  f"NIU : {client['niu']}" if client.get("niu") else None,
                  f"À l'attention de : {client['contact']}" if client.get("contact") else None):
            if v and str(v) != "nan":
                pdf.cell(0, 5.5, S(str(v)), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)
    if fac.get("objet") and str(fac["objet"]) != "nan":
        pdf.set_font("Helvetica", "B", 10)
        pdf.multi_cell(0, 5.5, S(f"Objet : {fac['objet']}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)
    larg = [22, 70, 28, 30, 40]
    pdf.set_fill_color(20, 83, 45)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 9)
    for w, t in zip(larg, ["Date", "Désignation", "Quantité", "Prix unitaire", "Montant HT (FCFA)"]):
        pdf.cell(w, 7, S(t), border=1, fill=True, align="C")
    pdf.ln()
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 8.5)
    for _, l in lignes.sort_values("date").iterrows():
        des = l["type"] + (f" — {l['site']}" if pd.notna(l["site"]) and l["site"] else "") + \
            (f" — compteur {l['compteur']}" if pd.notna(l["compteur"]) and l["compteur"] else "") + \
            (f" — réf. {l['reference']}" if pd.notna(l["reference"]) and l["reference"] else "")
        q = f"{m(l['quantite'])} {UNITES.get(l['type'], '')}" if pd.notna(l["quantite"]) else ""
        vals = [f"{l['date']:%d/%m/%Y}" if pd.notna(l["date"]) else "", des[:60], q,
                m(l["prix_unitaire"]) if pd.notna(l["prix_unitaire"]) else "", m(l["montant_ht"] or 0)]
        for w, t, a in zip(larg, vals, "CLRRR"):
            pdf.cell(w, 6, S(t), border=1, align=a)
        pdf.ln()
    pdf.ln(2)
    pdf.set_fill_color(220, 240, 226)
    for k, v, b in (("Total HT", fac["montant_ht"], False),
                    (f"TVA ({str(fac['taux_tva']).replace('.', ',')} %)", fac["montant_tva"], False),
                    ("Total TTC", fac["montant_ttc"], True)):
        pdf.set_x(120)
        pdf.set_font("Helvetica", "B" if b else "", 10)
        pdf.cell(40, 7, S(k), border=1, fill=b)
        pdf.cell(30, 7, S(m(v or 0)), border=1, align="R", fill=b, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 9.5)
    pdf.multi_cell(0, 5.5, S(f"Arrêtée la présente facture à la somme de {en_lettres(fac['montant_ttc'])} francs CFA "
                             f"toutes taxes comprises."), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if emetteur.get("paiement"):
        pdf.ln(3)
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5, S("Modalités de paiement : " + emetteur["paiement"]), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(10)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_x(120)
    pdf.cell(0, 6, S(emetteur.get("signataire") or "Pour l'Agence, le responsable habilité"), align="C")
    return bytes(pdf.output())
