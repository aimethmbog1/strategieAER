import io
import re

import pandas as pd
import plotly.express as px
import streamlit as st

from utils import clients_inst as ci
from utils.auth import peut_modifier
from utils.data import BLUE, GOLD, NAVY, RED
from utils.loader import get_data
from utils.parametres import memoriser, valeur
from utils.ui import PAGE_ICON, inject_base_style, kpi_row, plotly_base_layout, render_sidebar_footer, section_title

st.set_page_config(page_title="Clients institutionnels — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()
data = get_data()

st.title("🏢 Clients institutionnels — recharges et facturation")
st.caption("Suivi des opérateurs (MTN, IHS…) qui rechargent et achètent des compteurs : opérations, factures, "
           "paiements, reste à recouvrer et relevé de compte par client. Tout est enregistré dans la base.")

auj = pd.Timestamp(ci.maintenant()).normalize()
clients = ci.table("ci_clients")
op = ci.table("ci_operations")
fac = ci.table("ci_factures")
pay = ci.table("ci_paiements")
fs = ci.factures_avec_soldes(fac, pay, auj)
NOMS = dict(zip(clients["id"], clients["nom"]))
ACTIFS = clients.loc[clients["actif"], "id"].tolist()
nomc = lambda c: NOMS.get(c, c)
fm = lambda x, d=0: "—" if x is None or pd.isna(x) else f"{x:,.{d}f}".replace(",", " ").replace(".", ",")
M = lambda x: fm(x) + " F"
edit = peut_modifier()


def ok(msg):
    st.session_state["_ci_ok"] = msg
    st.rerun()


if st.session_state.get("_ci_ok"):
    st.success("💾 " + st.session_state.pop("_ci_ok"))

t_tb, t_saisie, t_fact, t_pay, t_rel, t_cli = st.tabs(["📊 Tableau de bord", "➕ Recharges et achats", "🧾 Facturation",
                                                       "💳 Paiements", "📒 Relevé client", "👥 Clients et tarifs"])

# ============================================================================= TABLEAU DE BORD
with t_tb:
    c1, c2 = st.columns([2, 3])
    dmin = min([d for d in [op["date"].min(), fac["date"].min()] if pd.notna(d)], default=auj - pd.Timedelta(days=365))
    per = c1.date_input("Période", (dmin.date(), auj.date()), key="ci_per", format="DD/MM/YYYY")
    sel = c2.multiselect("Clients (vide = tous)", sorted(set(clients["id"]) | set(op["client"].dropna())), format_func=nomc,
                         key="ci_sel")
    d0, d1 = (pd.Timestamp(per[0]), pd.Timestamp(per[1]) + pd.Timedelta(days=1)) if isinstance(per, tuple) and len(per) == 2 \
        else (dmin, auj + pd.Timedelta(days=1))
    o = op[op["date"].between(d0, d1)]
    f = fs[fs["date"].between(d0, d1)]
    if sel:
        o, f = o[o["client"].isin(sel)], f[f["client"].isin(sel)]
    fv = f[~f["annulee"]]
    rch = o[o["type"] == "Recharge"]
    kpi_row([("Énergie rechargée", f"{fm(rch['quantite'].sum())} kWh", f"{len(rch)} recharge(s)"),
             ("Ventes (HT)", M(o["montant_ht"].sum()), None),
             ("Compteurs achetés", fm(o.loc[o["type"] == "Achat de compteurs", "quantite"].sum()), None),
             ("Facturé (TTC)", M(fv["montant_ttc"].sum()), f"{len(fv)} facture(s)"),
             ("Encaissé", M(fv["paye"].sum()),
              f"{fm(100 * fv['paye'].sum() / fv['montant_ttc'].sum(), 1)} % recouvré" if fv["montant_ttc"].sum() else None),
             ("Reste à recouvrer", M(fs.loc[~fs["annulee"] & (fs["client"].isin(sel) if sel else True), "reste"].sum()),
              "toutes périodes")])
    non_fact = op[op["facture_id"].isna() & (op["client"].isin(sel) if sel else True)]
    if len(non_fact):
        st.warning(f"{len(non_fact)} opération(s) non encore facturée(s) pour {M(non_fact['montant_ht'].sum())} HT — "
                   "onglet « Facturation ».")
    echues = fs[fs["statut"].str.contains("chue", na=False) & (fs["client"].isin(sel) if sel else True)]
    if len(echues):
        st.error(f"{len(echues)} facture(s) échue(s) non soldée(s) : {M(echues['reste'].sum())} à relancer.")

    section_title("SYNTHÈSE PAR CLIENT (période choisie)")
    sy = ci.synthese_clients(o, f, pay, clients[clients["id"].isin(sel)] if sel else clients)
    if not sy.empty:
        st.dataframe(sy.drop(columns="code"), hide_index=True, width="stretch",
                     column_config={**{c: st.column_config.NumberColumn(format="localized") for c in sy.columns
                                       if "FCFA" in c or "kWh" in c},
                                    "Dernière recharge": st.column_config.DateColumn(format="DD/MM/YYYY"),
                                    "Taux de recouvrement (%)": st.column_config.ProgressColumn(format="%.1f %%", min_value=0, max_value=100)})
    if len(o):
        o2 = o.assign(Client=o["client"].map(nomc), Mois=o["date"].dt.to_period("M").dt.to_timestamp())
        PAL = [GOLD, NAVY, BLUE, RED, "#27AE60", "#8E44AD", "#16A085", "#7F8C8D"]
        COUL = {c: PAL[i % len(PAL)] for i, c in enumerate(sorted(o2["Client"].unique()))}

        def mois_axe(fig):
            fig.update_xaxes(tickformat="%b %Y", dtick="M1", ticklabelmode="period")
            return fig
        c1, c2 = st.columns(2)
        with c1:
            m_ = o2.groupby(["Mois", "Client"])["montant_ht"].sum().reset_index()
            fig = px.bar(m_, x="Mois", y="montant_ht", color="Client", title="Ventes mensuelles par client (FCFA HT)",
                         labels={"montant_ht": "FCFA", "Mois": ""}, color_discrete_map=COUL)
            fig.update_layout(barmode="stack", legend=dict(orientation="h", y=-0.25, title=None))
            st.plotly_chart(plotly_base_layout(mois_axe(fig), height=360), width="stretch")
        with c2:
            r_ = o2[o2["type"] == "Recharge"].groupby(["Mois", "Client"])["quantite"].sum().reset_index()
            fig = px.line(r_, x="Mois", y="quantite", color="Client", markers=True, title="Énergie rechargée par mois (kWh)",
                          labels={"quantite": "kWh", "Mois": ""}, color_discrete_map=COUL)
            fig.update_layout(legend=dict(orientation="h", y=-0.25, title=None))
            fig.update_yaxes(rangemode="tozero")
            st.plotly_chart(plotly_base_layout(mois_axe(fig), height=360), width="stretch")
        c1, c2 = st.columns(2)
        with c1:
            fig = px.pie(o2, names="Client", values="montant_ht", hole=0.5, title="Part de chaque client dans les ventes",
                         color="Client", color_discrete_map=COUL)
            st.plotly_chart(plotly_base_layout(fig, height=330), width="stretch")
        with c2:
            sites = o2[o2["site"].notna() & (o2["site"].astype(str) != "")]
            if len(sites):
                top = sites.groupby(["site", "Client"])["montant_ht"].sum().reset_index().sort_values("montant_ht").tail(15)
                fig = px.bar(top, x="montant_ht", y="site", color="Client", orientation="h", title="Principaux sites / localités", color_discrete_map=COUL,
                             labels={"montant_ht": "FCFA HT", "site": ""})
                st.plotly_chart(plotly_base_layout(fig, height=330), width="stretch")
    ag = ci.anciennete(fs[fs["client"].isin(sel)] if sel else fs)
    if len(ag):
        section_title("BALANCE ÂGÉE DU RESTE À RECOUVRER (FCFA)")
        ag.index = ag.index.map(nomc)
        ag["Total"] = ag.sum(axis=1)
        st.dataframe(ag.round(0), width="stretch", column_config={c: st.column_config.NumberColumn(format="localized") for c in ag.columns})

# ============================================================================= SAISIE
with t_saisie:
    s1, s2, s3 = st.tabs(["📝 Saisir une opération", "📥 Importer un fichier", "📋 Liste des opérations"])
    with s1:
        n = st.session_state.get("_ci_n", 0)
        c1, c2, c3 = st.columns(3)
        cli = c1.selectbox("Client", ACTIFS, format_func=nomc, key=f"ci_c_{n}")
        typ = c2.selectbox("Type d'opération", ci.TYPES_OP, key=f"ci_t_{n}")
        dte = c3.date_input("Date", value=auj.date(), key=f"ci_d_{n}", format="DD/MM/YYYY")
        fiche = clients.set_index("id").loc[cli] if cli in set(clients["id"]) else None
        pu_def = float((fiche["tarif_kwh"] if typ == "Recharge" else fiche["prix_compteur"] if typ == "Achat de compteurs" else 0) or 0) \
            if fiche is not None else 0.0
        c1, c2, c3 = st.columns(3)
        q = c1.number_input(f"Quantité ({ci.UNITES[typ]})", 0.0, 1e9, 0.0, 1.0, key=f"ci_q_{n}")
        pu = c2.number_input("Prix unitaire HT (FCFA)", 0.0, 1e9, pu_def, key=f"ci_pu_{n}_{cli}_{typ}",
                             help="Pré-rempli avec le tarif de la fiche client, modifiable.")
        mt = c3.number_input("Montant HT (FCFA)", 0.0, 1e12, q * pu, key=f"ci_mt_{n}_{q}_{pu}",
                             help="Calculé = quantité × prix ; saisis le montant réel s'il diffère.")
        c1, c2, c3 = st.columns(3)
        site = c1.text_input("Site / localité", key=f"ci_s_{n}")
        cpt = c2.text_input("N° de compteur(s)", key=f"ci_cp_{n}")
        ref = c3.text_input("Référence (token, bon de commande…)", key=f"ci_r_{n}")
        obs = st.text_input("Observations", key=f"ci_o_{n}")
        if st.button("💾 Enregistrer l'opération", type="primary", disabled=not (cli and mt > 0 and edit), key=f"ci_ok_{n}"):
            ids = ci.ajouter("ci_operations", [{"date": pd.Timestamp(dte), "client": cli, "type": typ, "site": site or None,
                                                "compteur": cpt or None, "quantite": q or None, "prix_unitaire": pu or None,
                                                "montant_ht": mt, "reference": ref or None, "observations": obs or None}],
                             "OP", f"{typ.lower()} {nomc(cli)} — {M(mt)}")
            st.session_state["_ci_n"] = n + 1
            ok(f"Opération {ids[0]} enregistrée.")
    with s2:
        st.caption("Fichier Excel ou CSV (export du système de vente, bordereau…). L'application reconnaît les colonnes "
                   "date, client, type, quantité / kWh, prix, montant, site, compteur, référence ; tu peux corriger le "
                   "rapprochement avant d'importer.")
        fic = st.file_uploader("Fichier", type=["xlsx", "xls", "csv"], key="ci_imp")
        if fic is not None:
            raw = pd.read_csv(fic, sep=None, engine="python") if fic.name.lower().endswith(".csv") else pd.read_excel(fic)
            raw = raw.dropna(how="all")
            cols = ["—"] + list(raw.columns)
            st.dataframe(raw.head(8), width="stretch")
            devine = ci.deviner_colonnes(raw)
            cs = st.columns(5)
            choix = {k: cs[i % 5].selectbox(k.replace("_", " ").capitalize(), cols,
                                            index=cols.index(devine[k]) if devine[k] else 0, key=f"ci_map_{k}")
                     for i, k in enumerate(ci.CHAMPS_IMPORT)}
            choix = {k: (None if v == "—" else v) for k, v in choix.items()}
            c1, c2 = st.columns(2)
            cli_def = c1.selectbox("Client (si absent du fichier)", ACTIFS, format_func=nomc, key="ci_imp_cli")
            typ_def = c2.selectbox("Type (si absent du fichier)", ci.TYPES_OP, key="ci_imp_typ")
            x = ci.preparer_import(raw, choix, cli_def, typ_def, NOMS)
            inconnus = sorted(set(x["client"]) - set(NOMS))
            st.caption(f"{len(x)} ligne(s) valides prêtes à importer · {M(x['montant_ht'].sum())} HT"
                       + (f" · ⚠️ clients inconnus : {', '.join(inconnus)} (ajoute-les dans « Clients et tarifs »)" if inconnus else ""))
            deja = op.assign(k=op["date"].astype(str) + op["client"].astype(str) + op["montant_ht"].astype(str) + op["reference"].astype(str))
            x["k"] = x["date"].astype(str) + x["client"].astype(str) + x["montant_ht"].astype(str) + x["reference"].astype(str)
            doublons = x["k"].isin(deja["k"]).sum()
            if doublons:
                st.info(f"{doublons} ligne(s) déjà présentes seront ignorées.")
            if st.button("📥 Importer", type="primary", disabled=x.empty or bool(inconnus) or not edit, key="ci_imp_ok"):
                neuf = x[~x["k"].isin(deja["k"])].drop(columns="k")
                ids = ci.ajouter("ci_operations", neuf.to_dict("records"), "OP", f"import {fic.name} : {len(neuf)} opération(s)")
                ok(f"{len(ids)} opération(s) importée(s).")
    with s3:
        c1, c2, c3 = st.columns(3)
        fc = c1.multiselect("Client", sorted(op["client"].dropna().unique()), format_func=nomc, key="ci_l_c")
        ft = c2.multiselect("Type", ci.TYPES_OP, key="ci_l_t")
        ff = c3.radio("Facturation", ["Toutes", "Non facturées", "Facturées"], horizontal=True, key="ci_l_f")
        v = op.copy()
        if fc:
            v = v[v["client"].isin(fc)]
        if ft:
            v = v[v["type"].isin(ft)]
        if ff != "Toutes":
            v = v[v["facture_id"].isna() == (ff == "Non facturées")]
        v = v.assign(client=v["client"].map(nomc)).sort_values("date", ascending=False)
        st.caption(f"{len(v)} opération(s) · {M(v['montant_ht'].sum())} HT")
        st.dataframe(v, hide_index=True, width="stretch", height=420,
                     column_config={"date": st.column_config.DateColumn(format="DD/MM/YYYY"),
                                    "montant_ht": st.column_config.NumberColumn("Montant HT", format="localized")})
        buf = io.BytesIO()
        v.to_excel(buf, index=False)
        st.download_button("⬇️ Exporter (Excel)", buf.getvalue(), "operations_clients_institutionnels.xlsx", key="ci_l_dl")
        libres = op[op["facture_id"].isna()]
        if len(libres) and edit:
            with st.expander("🗑️ Supprimer une opération non facturée (erreur de saisie)"):
                lab = {f"{r.id} — {nomc(r.client)} — {r.type} — {M(r.montant_ht)}": r.id for r in libres[::-1].itertuples()}
                oid = lab[st.selectbox("Opération", list(lab), key="ci_del")]
                if st.button("Supprimer", key="ci_del_ok"):
                    ci.sauver("ci_operations", op[op["id"] != oid], f"suppression de l'opération {oid}")
                    ok(f"{oid} supprimée.")

# ============================================================================= FACTURATION
with t_fact:
    emet = valeur("clients_inst", "emetteur", {}) or {}
    f1, f2, f3 = st.tabs(["🧾 Établir une facture", "📋 Factures émises", "⚙️ En-tête et TVA"])
    with f1:
        c1, c2, c3 = st.columns(3)
        cli = c1.selectbox("Client", sorted(set(op["client"].dropna()) | set(ACTIFS)), format_func=nomc, key="fa_c")
        libres = op[(op["client"] == cli) & op["facture_id"].isna()]
        if libres.empty:
            st.info("Aucune opération non facturée pour ce client.")
        else:
            pd0 = c2.date_input("Du", value=libres["date"].min().date(), key=f"fa_d0_{cli}", format="DD/MM/YYYY")
            pd1 = c3.date_input("Au", value=libres["date"].max().date(), key=f"fa_d1_{cli}", format="DD/MM/YYYY")
            l = libres[libres["date"].between(pd.Timestamp(pd0), pd.Timestamp(pd1) + pd.Timedelta(hours=23, minutes=59))]
            types = st.multiselect("Types à facturer", ci.TYPES_OP, default=sorted(l["type"].unique()), key=f"fa_t_{cli}")
            l = l[l["type"].isin(types)]
            st.dataframe(l[["id", "date", "type", "site", "compteur", "quantite", "prix_unitaire", "montant_ht", "reference"]],
                         hide_index=True, width="stretch", column_config={"date": st.column_config.DateColumn(format="DD/MM/YYYY")})
            c1, c2, c3, c4 = st.columns(4)
            tva_on = c1.checkbox("Soumis à la TVA", value=bool(emet.get("tva_on", True)), key="fa_tva_on")
            taux = c2.number_input("Taux de TVA (%)", 0.0, 50.0, float(emet.get("taux", ci.TVA_DEFAUT)), 0.25, key="fa_taux",
                                   disabled=not tva_on)
            dfa = c3.date_input("Date de la facture", value=auj.date(), key="fa_date", format="DD/MM/YYYY")
            fiche = clients.set_index("id").loc[cli] if cli in set(clients["id"]) else None
            delai = int((fiche["delai_paiement_j"] if fiche is not None and pd.notna(fiche["delai_paiement_j"]) else 30))
            ech = c4.date_input("Échéance", value=(pd.Timestamp(dfa) + pd.Timedelta(days=delai)).date(), key=f"fa_ech_{dfa}_{cli}",
                                format="DD/MM/YYYY")
            ht = l["montant_ht"].sum()
            tx = taux if tva_on else 0.0
            tva = round(ht * tx / 100)
            objet = st.text_input("Objet", value=f"{' et '.join(t.lower() for t in types)} — période du {pd0:%d/%m/%Y} au {pd1:%d/%m/%Y}",
                                  key=f"fa_obj_{cli}_{pd0}_{pd1}_{'-'.join(types)}")
            kpi_row([("Opérations", str(len(l)), None), ("Total HT", M(ht), None), ("TVA", M(tva), None), ("Total TTC", M(ht + tva), None)])
            if st.button("🧾 Établir la facture", type="primary", disabled=l.empty or not edit, key="fa_ok"):
                fid = ci.ajouter("ci_factures", [{"date": pd.Timestamp(dfa), "client": cli, "periode_debut": pd.Timestamp(pd0),
                                                  "periode_fin": pd.Timestamp(pd1), "objet": objet, "montant_ht": ht,
                                                  "taux_tva": tx, "montant_tva": tva, "montant_ttc": ht + tva,
                                                  "echeance": pd.Timestamp(ech), "annulee": False}],
                                 "FAC", f"facture {nomc(cli)} — {M(ht + tva)} TTC")[0]
                op2 = op.copy()
                op2.loc[op2["id"].isin(l["id"]), "facture_id"] = fid
                ci.sauver("ci_operations", op2, f"{len(l)} opération(s) rattachée(s) à {fid}")
                ok(f"Facture {fid} établie ({M(ht + tva)} TTC). Télécharge le PDF dans « Factures émises ».")
    with f2:
        if fs.empty:
            st.info("Aucune facture émise.")
        else:
            c1, c2 = st.columns(2)
            fc = c1.multiselect("Client", sorted(fs["client"].unique()), format_func=nomc, key="fe_c")
            fst = c2.multiselect("Statut", ["Émise", "Partiellement payée", "Échue", "Payée", "Annulée"], key="fe_s")
            v = fs.copy()
            if fc:
                v = v[v["client"].isin(fc)]
            if fst:
                v = v[v["statut"].apply(lambda s: any(s.startswith(x) or x in s for x in fst))]
            st.dataframe(v.assign(client=v["client"].map(nomc)).sort_values("date", ascending=False)[[
                "id", "date", "client", "objet", "montant_ht", "montant_tva", "montant_ttc", "paye", "reste", "echeance",
                "statut", "retard_j"]], hide_index=True, width="stretch", height=360,
                column_config={**{c: st.column_config.NumberColumn(format="localized") for c in
                                  ["montant_ht", "montant_tva", "montant_ttc", "paye", "reste"]},
                               "date": st.column_config.DateColumn(format="DD/MM/YYYY"),
                               "echeance": st.column_config.DateColumn("Échéance", format="DD/MM/YYYY"),
                               "retard_j": st.column_config.NumberColumn("Retard (j)")})
            c1, c2 = st.columns([3, 2])
            lab = {f"{r.id} — {nomc(r.client)} — {M(r.montant_ttc)} — {r.statut}": r.id for r in fs[::-1].itertuples()}
            fid = lab[c1.selectbox("Facture", list(lab), key="fe_sel")]
            r = fs.set_index("id").loc[fid]
            pdf = ci.facture_pdf(r.rename(index=None).to_dict() | {"id": fid}, op[op["facture_id"] == fid],
                                 clients.set_index("id").loc[r["client"]].to_dict() if r["client"] in set(clients["id"]) else None, emet)
            c2.download_button("⬇️ Facture PDF", pdf, f"{fid}.pdf", "application/pdf", key="fe_pdf", width="stretch")
            if edit and not r["annulee"] and r["paye"] == 0:
                if c2.button("⛔ Annuler cette facture", key="fe_ann", width="stretch"):
                    f2_ = fac.copy()
                    f2_.loc[f2_["id"] == fid, "annulee"] = True
                    ci.sauver("ci_factures", f2_, f"annulation de {fid}")
                    op2 = op.copy()
                    op2.loc[op2["facture_id"] == fid, "facture_id"] = None
                    ci.sauver("ci_operations", op2, f"opérations de {fid} remises à facturer")
                    ok(f"{fid} annulée ; ses opérations sont de nouveau à facturer.")
    with f3:
        st.caption("Informations imprimées sur les factures. Vérifie le régime de TVA applicable avec la Direction financière.")
        c1, c2 = st.columns(2)
        e = {"nom": c1.text_input("Émetteur", emet.get("nom", "Agence d'Électrification Rurale (AER)"), key="em_nom"),
             "adresse": c1.text_area("Adresse (une ligne par ligne)", emet.get("adresse", "Yaoundé — Cameroun"), key="em_adr"),
             "niu": c1.text_input("NIU de l'AER", emet.get("niu", ""), key="em_niu"),
             "paiement": c2.text_area("Modalités de paiement (banque, RIB…)", emet.get("paiement", ""), key="em_pay"),
             "signataire": c2.text_input("Signataire", emet.get("signataire", "Pour l'Agence, le responsable habilité"), key="em_sig"),
             "tva_on": c2.checkbox("Factures soumises à la TVA par défaut", bool(emet.get("tva_on", True)), key="em_tva"),
             "taux": c2.number_input("Taux de TVA par défaut (%)", 0.0, 50.0, float(emet.get("taux", ci.TVA_DEFAUT)), 0.25, key="em_tx")}
        if edit:
            memoriser("clients_inst", "emetteur", e)

# ============================================================================= PAIEMENTS
with t_pay:
    ouvertes = fs[(fs["reste"] > 0.5) & ~fs["annulee"]]
    if ouvertes.empty:
        st.info("Aucune facture en attente de paiement.")
    else:
        n = st.session_state.get("_pa_n", 0)
        c1, c2 = st.columns([3, 1])
        lab = {f"{r.id} — {nomc(r.client)} — reste {M(r.reste)} — {r.statut}": r.id for r in ouvertes.itertuples()}
        fid = lab[c1.selectbox("Facture", list(lab), key=f"pa_f_{n}")]
        r = ouvertes.set_index("id").loc[fid]
        mt = c2.number_input("Montant reçu (FCFA)", 0.0, float(r["reste"]), float(r["reste"]), key=f"pa_m_{n}_{fid}")
        c1, c2, c3 = st.columns(3)
        dp = c1.date_input("Date de paiement", value=auj.date(), key=f"pa_d_{n}", format="DD/MM/YYYY")
        mode = c2.selectbox("Mode", ci.MODES_PAIEMENT, key=f"pa_mo_{n}")
        refp = c3.text_input("Référence (n° de virement, chèque…)", key=f"pa_r_{n}")
        if st.button("💳 Enregistrer le paiement", type="primary", disabled=not (mt > 0 and edit), key=f"pa_ok_{n}"):
            ci.ajouter("ci_paiements", [{"date": pd.Timestamp(dp), "facture_id": fid, "client": r["client"], "montant": mt,
                                         "mode": mode, "reference": refp or None}], "PAY",
                       f"paiement {nomc(r['client'])} {M(mt)} sur {fid}")
            st.session_state["_pa_n"] = n + 1
            ok(f"Paiement de {M(mt)} enregistré sur {fid}.")
    if len(pay):
        section_title("PAIEMENTS REÇUS")
        st.dataframe(pay.assign(client=pay["client"].map(nomc)).sort_values("date", ascending=False), hide_index=True,
                     width="stretch", column_config={"date": st.column_config.DateColumn(format="DD/MM/YYYY"),
                                                     "montant": st.column_config.NumberColumn(format="localized")})

# ============================================================================= RELEVÉ
with t_rel:
    cli = st.selectbox("Client", sorted(set(clients["id"]) | set(op["client"].dropna())), format_func=nomc, key="rl_c")
    ff = fs[(fs["client"] == cli) & ~fs["annulee"]]
    pp = pay[pay["client"] == cli]
    mv = pd.concat([pd.DataFrame({"Date": ff["date"], "Pièce": ff["id"], "Libellé": "Facture — " + ff["objet"].fillna(""),
                                  "Débit": ff["montant_ttc"], "Crédit": 0.0}),
                    pd.DataFrame({"Date": pp["date"], "Pièce": pp["id"],
                                  "Libellé": "Paiement " + pp["mode"].fillna("") + " — " + pp["facture_id"].fillna(""),
                                  "Débit": 0.0, "Crédit": pp["montant"]})], ignore_index=True).sort_values(["Date", "Pièce"])
    mv["Solde"] = (mv["Débit"] - mv["Crédit"]).cumsum()
    o = op[op["client"] == cli]
    kpi_row([("Total facturé", M(ff["montant_ttc"].sum()), None), ("Total encaissé", M(pp["montant"].sum()), None),
             ("Solde dû", M(ff["reste"].sum()), None), ("Non facturé (HT)", M(o.loc[o["facture_id"].isna(), "montant_ht"].sum()), None),
             ("Délai moyen de paiement", f"{fm(ff['delai_paiement_j'].mean())} j", None)])
    st.dataframe(mv, hide_index=True, width="stretch", height=380,
                 column_config={"Date": st.column_config.DateColumn(format="DD/MM/YYYY"),
                                **{c: st.column_config.NumberColumn(format="localized") for c in ["Débit", "Crédit", "Solde"]}})
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as xw:
        mv.to_excel(xw, sheet_name="Relevé", index=False)
        o.to_excel(xw, sheet_name="Opérations", index=False)
        ff.to_excel(xw, sheet_name="Factures", index=False)
    st.download_button(f"⬇️ Relevé de compte {nomc(cli)} (Excel)", buf.getvalue(), f"releve_{cli}_{auj:%Y%m%d}.xlsx", key="rl_dl")

# ============================================================================= CLIENTS
with t_cli:
    st.caption("Fiche de chaque client : coordonnées imprimées sur les factures, délai de paiement et tarifs par défaut "
               "(prix du kWh rechargé, prix d'un compteur). Ajoute une ligne pour un nouveau client ; le code (MTN, IHS…) "
               "ne doit plus changer une fois des opérations saisies.")
    ed = st.data_editor(clients, num_rows="dynamic", hide_index=True, width="stretch", key="cl_ed", disabled=not edit,
                        column_config={"id": st.column_config.TextColumn("Code", required=True),
                                       "nom": st.column_config.TextColumn("Nom", required=True),
                                       "raison_sociale": "Raison sociale", "niu": "NIU", "adresse": "Adresse",
                                       "contact": "Interlocuteur", "email": "Courriel",
                                       "delai_paiement_j": st.column_config.NumberColumn("Délai de paiement (j)", min_value=0),
                                       "tarif_kwh": st.column_config.NumberColumn("Tarif kWh HT (FCFA)", min_value=0),
                                       "prix_compteur": st.column_config.NumberColumn("Prix compteur HT (FCFA)", min_value=0),
                                       "actif": "Actif", "observations": "Observations"})
    if edit and st.button("💾 Enregistrer les clients", key="cl_ok"):
        ed = ed.dropna(subset=["id", "nom"])
        if ed["id"].duplicated().any():
            st.error("Deux clients ont le même code.")
        else:
            ci.sauver("ci_clients", ed, "fiches clients institutionnels")
            ok("Fiches clients enregistrées.")

render_sidebar_footer(data.generated_on if data else "")
