import plotly.express as px
import streamlit as st

from utils.data import NAVY, BLUE, GOLD, CATEGORICAL
from utils.loader import get_data
from utils.personnel import get_effective_roster
from utils.paie import (
    COLS_REGISTRE, ELEMENTS_GAINS, MONTANTS, calculer_masse, get_registre, lire_import, parametres_session,
    registre_depuis_personnel, reinitialiser_parametres, set_registre, ventiler, vers_excel,
    PROFILS_COLS, duree_essai_statutaire, profils_exemple, simuler_recrutement,
)
from utils.auth import ROLES_PAIE, require_role
from utils.storage import enregistrer_si_change, session_ou_stockage
from utils.ui import PAGE_ICON, inject_base_style, section_title, plotly_base_layout, kpi_row, render_sidebar_footer

from utils.parametres import memoriser, valeur
st.set_page_config(page_title="Masse salariale — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()
require_role(ROLES_PAIE, "la masse salariale (données nominatives de paie)")

data = get_data()
if data is None:
    st.stop()

st.title("💼 Masse salariale")
st.caption("Calcul conforme au Statut du personnel de l'AER (CA du 22 janvier 2020) : grille des salaires, "
           "indemnités et primes par catégorie et par palier, retenues légales (CNPS, CFC, IRPP, CAC, RAV, TDL) "
           "et charges patronales. Le registre de paie vit en session : exportez-le pour le conserver.")

eq, unassigned = get_effective_roster(data.equipes_rows, data.unassigned)
P = parametres_session()
reg = get_registre(eq, unassigned)

tab_reg, tab_masse, tab_vent, tab_bull, tab_recr, tab_proj, tab_param = st.tabs(
    ["🧾 Registre de paie", "📊 Masse salariale & tris", "🧮 Ventilations", "📄 Bulletin individuel",
     "🆕 Simulation de recrutement", "📈 Projection & CNPS", "⚙️ Paramètres"])

# ------------------------------------------------------------------ Registre
with tab_reg:
    section_title("REGISTRE DE PAIE — SAISIE")
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        fichier = st.file_uploader("Importer un registre (onglet « Paie » du classeur Calcul_Salaires_AER.xlsx, "
                                   "ou CSV/Excel aux colonnes du registre)", type=["xlsx", "csv"], key="paie_import")
        if fichier is not None and st.session_state.get("paie_import_nom") != fichier.name:
            try:
                set_registre(lire_import(fichier))
                st.session_state["paie_import_nom"] = fichier.name
                st.success(f"{len(get_registre(eq, unassigned))} agent(s) importé(s) depuis {fichier.name}.")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Import impossible : {exc}")
    with c2:
        st.write("")
        if st.button("↺ Repartir du personnel de l'application", width="stretch"):
            set_registre(registre_depuis_personnel(eq, unassigned))
            st.session_state.pop("paie_import_nom", None)
            st.rerun()
    with c3:
        st.write("")
        st.download_button("⬇️ Exporter le registre (CSV)", reg.to_csv(index=False).encode("utf-8"),
                           "registre_paie_aer.csv", "text/csv", width="stretch")

    a_completer = int(reg["Catégorie"].isna().sum() + reg["Échelon"].isna().sum())
    if a_completer:
        st.info("Le classeur RH de l'application ne contient ni catégorie ni échelon : complétez ces deux colonnes "
                "pour que l'agent entre dans le calcul (les lignes incomplètes sont listées dans l'onglet suivant).")

    on = ["Oui", "Non"]
    cfg = {
        "Statut": st.column_config.SelectboxColumn(options=list(P["STATUTS"]), required=True),
        "Catégorie": st.column_config.NumberColumn(min_value=1, max_value=12, step=1),
        "Échelon": st.column_config.SelectboxColumn(options=P["ECHELONS"]),
        "Palier": st.column_config.SelectboxColumn(options=P["PALIERS"], required=True,
                                                   help="P1 Chef de service · P2 Sous-Directeur / Chef de Cellule / "
                                                        "Chef d'Antenne · P3 Directeur / Conseiller Technique / Chef de Division"),
        "Intérim — palier": st.column_config.SelectboxColumn(options=P["PALIERS"], required=True),
        "Intérim — durée (mois)": st.column_config.NumberColumn(min_value=0, step=0.5),
        "Cabinet (astreinte)": st.column_config.SelectboxColumn(options=on, required=True),
        "Enfants mineurs": st.column_config.NumberColumn(min_value=0, step=1),
        "Situation du mois": st.column_config.SelectboxColumn(options=list(P["SITUATIONS"]), required=True),
        "Jours non payés": st.column_config.NumberColumn(min_value=0, max_value=30, step=1),
        "Mois de présence": st.column_config.NumberColumn(min_value=0, max_value=12, step=1),
        "13e mois ce mois": st.column_config.SelectboxColumn(options=on, required=True),
        "Prime d'installation ce mois": st.column_config.SelectboxColumn(options=on, required=True),
        "Médaille ce mois": st.column_config.SelectboxColumn(options=["Aucune", "Argent", "Vermeil", "Or"], required=True),
    }
    for c in ("Gratification exceptionnelle", "Autres gains imposables", "Autres gains non imposables",
              "Avance sur salaire (retenue)", "Autres retenues"):
        cfg[c] = st.column_config.NumberColumn(min_value=0, step=1000, format="%d")
    edite = st.data_editor(reg, column_config=cfg, num_rows="dynamic", width="stretch",
                           hide_index=True, height=480, key=f"paie_editor_{st.session_state.get('paie_ver', 0)}")
    if st.button("💾 Appliquer les modifications au calcul", type="primary"):
        set_registre(edite)
        st.success("Registre mis à jour.")
        st.rerun()

# ------------------------------------------------------------------ Paramètres
with tab_param:
    section_title("OPTIONS D'INTERPRÉTATION DU STATUT (session)")
    st.caption("Ces réglages s'appliquent à toute la session ; les valeurs par défaut viennent de "
               "data/parametres_paie_aer.json. Les points marqués « à valider » relèvent de la DRH, de la DGI ou de la CNPS.")
    O = P["OPTIONS"]
    if not st.session_state.get("_paie_reglages_charges"):  # une fois par session : réglages enregistrés
        O.update(valeur("paie", "options", {}) or {})
        P["PATRONAL"]["at"] = float(valeur("paie", "taux_at", P["PATRONAL"]["at"]))
        st.session_state["_paie_reglages_charges"] = True
    modes = ["Forfait palier", "Plafond", "Plus favorable"]
    c1, c2 = st.columns(2)
    with c1:
        for cle, lib in (("mode_logement", "Responsables — indemnité de logement"),
                         ("mode_deplacement", "Responsables — indemnité de déplacement"),
                         ("mode_technicite", "Responsables — prime de technicité"),
                         ("mode_af", "Responsables — allocation familiale")):
            O[cle] = st.selectbox(lib + " (« plafonnée à » : à valider)", modes, index=modes.index(O[cle]), key=f"opt_{cle}")
    with c2:
        for cle, lib in (("supplement_enfant_responsables", "Supplément 2 400 F/enfant ajouté au montant du palier"),
                         ("carburant_en_paie", "Dotation carburant versée en paie"),
                         ("communication_en_paie", "Crédit de communication versé en paie")):
            O[cle] = st.radio(lib, ["Oui", "Non"], index=["Oui", "Non"].index(O[cle]), horizontal=True, key=f"opt_{cle}")
        O["base_13e_mois"] = st.radio("Base du 13e mois", ["Salaire de base", "Brut récurrent"],
                                      index=["Salaire de base", "Brut récurrent"].index(O["base_13e_mois"]),
                                      horizontal=True, key="opt_base13")
        P["PATRONAL"]["at"] = st.number_input("Taux patronal accidents du travail (à valider)", 0.0, 0.10,
                                              float(P["PATRONAL"]["at"]), 0.0025, format="%.4f", key="opt_at")
    memoriser("paie", "options", dict(O))
    memoriser("paie", "taux_at", float(P["PATRONAL"]["at"]))
    st.caption("💾 Ces réglages sont enregistrés dans la base et s'appliquent à tous les utilisateurs.")
    if st.button("↺ Revenir aux paramètres par défaut"):
        reinitialiser_parametres()
        P0 = parametres_session()
        memoriser("paie", "options", dict(P0["OPTIONS"]))
        memoriser("paie", "taux_at", float(P0["PATRONAL"]["at"]))
        for k in list(st.session_state):
            if k.startswith("opt_"):
                st.session_state.pop(k)
        st.rerun()
    with st.expander("Grille des salaires de base (art. 24)"):
        import pandas as pd
        st.dataframe(pd.DataFrame(P["GRILLE"], index=P["ECHELONS"]).T.rename_axis("Catégorie"),
                     width="stretch")

res, exclus = calculer_masse(get_registre(eq, unassigned), P)

# ------------------------------------------------------------------ Masse & tris
with tab_masse:
    if res.empty:
        st.warning("Aucun agent calculable : renseignez au moins la catégorie et l'échelon dans le registre.")
    else:
        section_title("FILTRES")
        f1, f2, f3, f4 = st.columns(4)
        f_ant = f1.multiselect("Antenne", sorted(res["Antenne"].dropna().astype(str).unique()))
        f_grp = f2.multiselect("Groupe", sorted(res["Groupe"].unique()))
        f_cat = f3.multiselect("Catégorie", sorted(res["Catégorie"].unique()))
        f_pal = f4.multiselect("Palier effectif", sorted(res["Palier effectif"].unique()))
        f5, f6, f7, f8 = st.columns(4)
        f_st = f5.multiselect("Statut", sorted(res["Statut"].astype(str).unique()))
        f_sit = f6.multiselect("Situation du mois", sorted(res["Situation du mois"].astype(str).unique()))
        bmin, bmax = int(res["Brut"].min()), int(res["Brut"].max())
        f_brut = f7.slider("Fourchette de brut (FCFA)", bmin, max(bmax, bmin + 1), (bmin, max(bmax, bmin + 1)), step=5000)
        f_txt = f8.text_input("Rechercher (nom ou matricule)")

        v = res.copy()
        for col, sel in (("Antenne", f_ant), ("Groupe", f_grp), ("Catégorie", f_cat), ("Palier effectif", f_pal),
                         ("Statut", f_st), ("Situation du mois", f_sit)):
            if sel:
                v = v[v[col].astype(str).isin([str(s) for s in sel])]
        v = v[(v["Brut"] >= f_brut[0]) & (v["Brut"] <= f_brut[1])]
        if f_txt:
            m = v["Nom"].astype(str).str.contains(f_txt, case=False, na=False) | \
                v["Matricule"].astype(str).str.contains(f_txt, case=False, na=False)
            v = v[m]

        section_title("TRI")
        t1, t2, t3, t4 = st.columns([2, 2, 1, 1])
        cle1 = t1.selectbox("Trier par", ["Coût employeur", "Brut", "Net à payer", "Salaire de base", "IRPP",
                                          "Charges patronales", "Nom", "Matricule", "Antenne", "Catégorie",
                                          "Échelon", "Palier effectif", "Groupe", "Statut"] +
                            [c for c in MONTANTS if c not in ("Coût employeur", "Brut", "Net à payer",
                                                              "Salaire de base", "IRPP", "Charges patronales")])
        cle2 = t2.selectbox("Puis par", ["(aucun)", "Nom", "Antenne", "Catégorie", "Échelon", "Palier effectif",
                                         "Brut", "Net à payer", "Coût employeur"])
        ordre = t3.radio("Ordre", ["Décroissant", "Croissant"], horizontal=False)
        top = t4.number_input("Afficher les N premiers (0 = tous)", min_value=0, value=0, step=5)
        cles = [cle1] + ([cle2] if cle2 != "(aucun)" and cle2 != cle1 else [])
        v = v.sort_values(cles, ascending=(ordre == "Croissant"), kind="mergesort")
        if top:
            v = v.head(int(top))

        kpi_row([
            ("Effectif", f"{len(v):,}".replace(",", " "), None),
            ("Masse brute mensuelle", f"{v['Brut'].sum():,.0f} F".replace(",", " "), None),
            ("Net à payer mensuel", f"{v['Net à payer'].sum():,.0f} F".replace(",", " "), None),
            ("Charges patronales", f"{v['Charges patronales'].sum():,.0f} F".replace(",", " "), None),
            ("Coût employeur mensuel", f"{v['Coût employeur'].sum():,.0f} F".replace(",", " "), None),
            ("Coût employeur annuel (× 12)", f"{v['Coût employeur'].sum() * 12:,.0f} F".replace(",", " "), None),
        ])
        st.caption("Le coût annuel est le coût du mois × 12 : il n'inclut pas de 13e mois ni de prime ponctuelle "
                   "qui ne serait pas saisie ce mois-ci.")

        colonnes = st.multiselect("Colonnes affichées", list(v.columns),
                                  default=["Matricule", "Nom", "Antenne", "Catégorie", "Échelon", "Palier effectif",
                                           "Salaire de base", "Brut", "Total retenues", "Net à payer",
                                           "Charges patronales", "Coût employeur"])
        fmt = {c: st.column_config.NumberColumn(format="%d") for c in MONTANTS if c in colonnes}
        st.dataframe(v[colonnes], width="stretch", hide_index=True, height=480, column_config=fmt)
        st.caption(f"{len(v)} agent(s) affiché(s) sur {len(res)} calculé(s). Cliquez sur un en-tête de colonne pour "
                   "un tri rapide supplémentaire.")
        d1, d2 = st.columns(2)
        d1.download_button("⬇️ Sélection (CSV)", v.to_csv(index=False).encode("utf-8"), "masse_salariale.csv",
                           "text/csv", width="stretch")
        d2.download_button("⬇️ Sélection + ventilations (Excel)",
                           vers_excel({"Détail": v, "Par antenne": ventiler(v, "Antenne"),
                                       "Par catégorie": ventiler(v, "Catégorie"),
                                       "Par palier": ventiler(v, "Palier effectif"), "Par groupe": ventiler(v, "Groupe")}),
                           "masse_salariale_aer.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")

    if not exclus.empty:
        with st.expander(f"⚠️ {len(exclus)} ligne(s) exclue(s) du calcul"):
            st.dataframe(exclus, width="stretch", hide_index=True)

# ------------------------------------------------------------------ Ventilations
with tab_vent:
    if res.empty:
        st.warning("Aucun agent calculable.")
    else:
        section_title("VENTILATION DE LA MASSE SALARIALE")
        c1, c2 = st.columns([1, 1])
        dim = c1.selectbox("Ventiler par", ["Antenne", "Catégorie", "Groupe", "Palier effectif", "Échelon",
                                            "Statut", "Poste RH", "Situation du mois"])
        mesure = c2.selectbox("Mesure", ["Coût employeur", "Brut", "Net", "Charges patronales", "Retenues",
                                         "Effectif", "Brut moyen"])
        tv = ventiler(res, dim).sort_values(mesure, ascending=False)
        g1, g2 = st.columns([3, 2])
        with g1:
            fig = px.bar(tv, x=mesure, y=tv[dim].astype(str), orientation="h", color_discrete_sequence=[NAVY],
                         title=f"{mesure} par {dim.lower()}")
            fig = plotly_base_layout(fig, height=max(320, 28 * len(tv) + 80), legend=False)
            fig.update_layout(yaxis_title=None, yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig, width="stretch")
        with g2:
            fmt = {c: st.column_config.NumberColumn(format="%d") for c in
                   ("Brut", "Net", "Retenues", "Charges patronales", "Coût employeur", "Brut moyen")}
            st.dataframe(tv, width="stretch", hide_index=True, column_config=fmt, height=420)

        section_title("STRUCTURE DE LA MASSE BRUTE")
        comp = res[[c for c in ELEMENTS_GAINS if c in res.columns]].sum().reset_index()
        comp.columns = ["Élément", "Montant"]
        comp = comp[comp["Montant"] > 0].sort_values("Montant", ascending=True)
        comp["Part (%)"] = (comp["Montant"] / comp["Montant"].sum() * 100).round(1)
        fig = px.bar(comp, x="Montant", y="Élément", orientation="h", text="Part (%)",
                     color_discrete_sequence=[BLUE], title="Éléments de rémunération (mois en cours)")
        fig.update_traces(texttemplate="%{text} %", textposition="outside")
        st.plotly_chart(plotly_base_layout(fig, height=420, legend=False), width="stretch")
        st.caption("Les montants bruts tiennent compte du coefficient de maintien (situation du mois, jours non payés).")

# ------------------------------------------------------------------ Bulletin
with tab_bull:
    if res.empty:
        st.warning("Aucun agent calculable.")
    else:
        choix = st.selectbox("Agent", (res["Matricule"].astype(str) + " — " + res["Nom"].astype(str)).tolist())
        ligne = res.iloc[(res["Matricule"].astype(str) + " — " + res["Nom"].astype(str)).tolist().index(choix)]
        c1, c2, c3 = st.columns(3)
        with c1:
            section_title("IDENTIFICATION")
            for k in ("Matricule", "Nom", "Antenne", "Poste RH", "Statut", "Catégorie", "Échelon", "Groupe",
                      "Palier", "Palier effectif", "Situation du mois"):
                st.markdown(f"**{k}** : {ligne[k]}")
        with c2:
            section_title("GAINS")
            for k in ELEMENTS_GAINS:
                if ligne[k]:
                    st.markdown(f"{k} : **{ligne[k]:,.0f} F**".replace(",", " "))
            st.markdown(f"### Brut : {ligne['Brut']:,.0f} F".replace(",", " "))
        with c3:
            section_title("RETENUES & NET")
            for k in ("CNPS salarié", "CFC salarié", "IRPP", "CAC", "RAV", "TDL", "Total retenues"):
                st.markdown(f"{k} : **{ligne[k]:,.0f} F**".replace(",", " "))
            st.markdown(f"### Net à payer : {ligne['Net à payer']:,.0f} F".replace(",", " "))
            st.caption(f"Charges patronales : {ligne['Charges patronales']:,.0f} F · coût employeur : "
                       f"{ligne['Coût employeur']:,.0f} F".replace(",", " "))
        from utils.rapports import build_pdf_report
        mois_paie = st.text_input("Mois de paie (pour la fiche)", pd.Timestamp.today().strftime("%m/%Y"), key="bull_mois")
        lignes_g = pd.DataFrame([{"Élément": k, "Montant (FCFA)": f"{ligne[k]:,.0f}".replace(",", " ")}
                                 for k in ELEMENTS_GAINS if ligne[k]] +
                                [{"Élément": "SALAIRE BRUT", "Montant (FCFA)": f"{ligne['Brut']:,.0f}".replace(",", " ")}])
        lignes_r = pd.DataFrame([{"Retenue": k, "Montant (FCFA)": f"{ligne[k]:,.0f}".replace(",", " ")}
                                 for k in ("CNPS salarié", "CFC salarié", "IRPP", "CAC", "RAV", "TDL", "Total retenues")])
        ident = (f"Matricule {ligne['Matricule']} - {ligne['Nom']} - {ligne['Antenne'] or ''} - catégorie "
                 f"{ligne['Catégorie']}, échelon {ligne['Échelon']}, palier {ligne['Palier effectif']} - "
                 f"situation : {ligne['Situation du mois']}")
        pdf = build_pdf_report(f"Fiche de paie - {mois_paie}", "Agence d'Électrification Rurale", pd.Timestamp.now().strftime("%d/%m/%Y"),
                               [("Brut", f"{ligne['Brut']:,.0f} F".replace(",", " ")),
                                ("Retenues", f"{ligne['Total retenues']:,.0f} F".replace(",", " ")),
                                ("Net à payer", f"{ligne['Net à payer']:,.0f} F".replace(",", " "))],
                               [{"titre": "Agent", "texte": ident, "image_bytes": None, "tableau": None},
                                {"titre": "Gains", "texte": None, "image_bytes": None, "tableau": lignes_g},
                                {"titre": "Retenues", "texte": None, "image_bytes": None, "tableau": lignes_r},
                                {"titre": "Information", "texte": "Document calculé selon le Statut du personnel de l'AER "
                                 "(CA du 22/01/2020) et les retenues légales en vigueur ; à valider par le service de la paie.",
                                 "image_bytes": None, "tableau": None}])
        st.download_button("⬇️ Fiche de paie (PDF)", pdf, f"fiche_paie_{ligne['Matricule']}.pdf", "application/pdf")

# ------------------------------------------------------------------ Projection pluriannuelle
with tab_proj:
    st.caption("Projection de la masse salariale sur trois exercices, pour le cadrage budgétaire (CDMT). Base : le "
               "registre de paie actuel, annualisé ; s'y ajoutent, si vous le souhaitez, les recrutements simulés dans "
               "l'onglet « Simulation de recrutement ».")
    if res.empty:
        st.warning("Renseignez d'abord le registre de paie.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        pj = valeur("paie", "projection", {})
        an0 = c1.number_input("Premier exercice", 2025, 2040, int(pj.get("an0", max(2027, pd.Timestamp.today().year + 1))), step=1)
        reval = c2.number_input("Revalorisation annuelle de la grille (%)", 0.0, 20.0, float(pj.get("reval", 0.0)), 0.5) / 100
        attr = c3.number_input("Départs non remplacés par an (%)", 0.0, 30.0, float(pj.get("attr", 0.0)), 0.5) / 100
        memoriser("paie", "projection", {"an0": int(an0), "reval": round(reval * 100, 2), "attr": round(attr * 100, 2)})
        avance = c4.checkbox("Avancement d'échelon de droit (art. 10)", value=True,
                             help="Approximation : la moitié des agents avance d'un échelon en N+1, tous en N+2 (G maximum).")
        avec_recr = st.checkbox("Ajouter les recrutements simulés (onglet Simulation de recrutement)", value=True)
        from utils.paie import calculer_masse as _cm
        reg_now = get_registre(eq, unassigned)
        lignes_p = []
        for k in range(3):
            r = reg_now.copy()
            if avance and k > 0:
                idx = r.index if k >= 2 else r.index[::2]
                ech = r.loc[idx, "Échelon"].astype(str)
                r.loc[idx, "Échelon"] = ech.map(lambda e: P["ECHELONS"][min(P["ECHELONS"].index(e) + 1, 6)]
                                                if e in P["ECHELONS"] else e)
            rk, _ = _cm(r, P)
            facteur = (1 + reval) ** k * (1 - attr) ** k
            brut = rk["Brut"].sum() * 12 * facteur
            cout = rk["Coût employeur"].sum() * 12 * facteur
            recr = 0.0
            if avec_recr:
                from utils.storage import charger as _charger
                prof = _charger("recr_profils")
                prof = prof if prof is not None else st.session_state.get("recr_profils")
                if prof is not None and not prof.empty:
                    dk, _ = simuler_recrutement(prof, f"{an0 + k}-01-01", f"{an0 + k}-12-01", P, avancement=avance)
                    recr = dk["Coût employeur"].sum() * (1 + reval) ** k if not dk.empty else 0.0
            lignes_p.append({"Exercice": str(an0 + k), "Masse brute (personnel en place)": round(brut),
                             "Coût employeur (personnel en place)": round(cout), "Coût des recrutements": round(recr),
                             "Coût employeur total": round(cout + recr)})
        proj = pd.DataFrame(lignes_p)
        fig = px.bar(proj.melt(id_vars="Exercice", value_vars=["Coût employeur (personnel en place)", "Coût des recrutements"],
                               var_name="Composante", value_name="FCFA"),
                     x="Exercice", y="FCFA", color="Composante", barmode="stack",
                     color_discrete_sequence=[NAVY, GOLD], title="Coût employeur annuel projeté (FCFA)")
        st.plotly_chart(plotly_base_layout(fig, height=380), width="stretch")
        st.dataframe(proj, width="stretch", hide_index=True,
                     column_config={c: st.column_config.NumberColumn(format="%d") for c in proj.columns if c != "Exercice"})
        st.caption("Hypothèses : registre du mois courant × 12 ; pas de 13e mois ni de prime ponctuelle ; revalorisation "
                   "et départs appliqués uniformément ; recrutements selon la simulation (périodes d'essai comprises).")
        st.download_button("⬇️ Projection (Excel)", vers_excel({"Projection": proj}), "projection_masse_salariale.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    section_title("RÉCAPITULATIF CNPS DU MOIS")
    if not res.empty:
        cnps_cols = ["Matricule", "Nom", "Statut", "Brut", "Brut soumis CNPS", "CNPS salarié", "CNPS vieillesse (patronal)",
                     "Prestations familiales (patronal)", "Accidents du travail (patronal)"]
        rc = res[cnps_cols].copy()
        rc["Total cotisations CNPS"] = rc[["CNPS salarié", "CNPS vieillesse (patronal)", "Prestations familiales (patronal)",
                                          "Accidents du travail (patronal)"]].sum(axis=1)
        st.dataframe(rc, width="stretch", hide_index=True,
                     column_config={c: st.column_config.NumberColumn(format="%d") for c in rc.columns[3:]})
        st.caption(f"Total à déclarer : {rc['Total cotisations CNPS'].sum():,.0f} FCFA. Récapitulatif de contrôle ; le "
                   "format officiel de déclaration (DIPE) reste à produire dans l'outil de la CNPS.".replace(",", " "))
        st.download_button("⬇️ Récapitulatif CNPS (Excel)", vers_excel({"CNPS": rc}), "recap_cnps.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ------------------------------------------------------------------ Simulation de recrutement
with tab_recr:
    import pandas as pd
    st.caption("Simule le coût d'un personnel à recruter sur une période donnée. Pendant la période d'essai, "
               "l'agent ne perçoit que son salaire de base ; à l'issue de l'essai, les indemnités et primes de sa "
               "catégorie (et de son palier) s'y ajoutent. Retenues légales et charges patronales comprises.")
    section_title("PÉRIODE DE SIMULATION")
    aujourd_hui = pd.Timestamp.today().normalize()
    debut_def = (aujourd_hui + pd.offsets.MonthBegin(1)).date()
    c1, c2, c3 = st.columns([1, 1, 2])
    debut = c1.date_input("Premier mois", value=debut_def, format="DD/MM/YYYY", key="recr_debut")
    fin = c2.date_input("Dernier mois", value=(pd.Timestamp(debut_def) + pd.DateOffset(months=11)).date(),
                        format="DD/MM/YYYY", key="recr_fin")
    avancement = c3.checkbox("Appliquer l'avancement d'échelon de droit tous les 24 mois (art. 10 b)", value=False)
    if pd.Timestamp(fin).to_period("M") < pd.Timestamp(debut).to_period("M"):
        st.error("Le dernier mois doit être postérieur ou égal au premier mois.")
        st.stop()
    nb_mois = (pd.Timestamp(fin).to_period("M") - pd.Timestamp(debut).to_period("M")).n + 1
    st.caption(f"Période : {nb_mois} mois, de {pd.Timestamp(debut):%m/%Y} à {pd.Timestamp(fin):%m/%Y}. "
               "Chaque embauche est réputée prendre effet le 1er du mois indiqué.")

    section_title("PERSONNEL À RECRUTER")
    session_ou_stockage("recr_profils", lambda: profils_exemple(debut))
    b1, b2 = st.columns([1, 3])
    if b1.button("↺ Repartir de l'exemple", key="recr_reset"):
        st.session_state["recr_profils"] = profils_exemple(debut)
        enregistrer_si_change("recr_profils", st.session_state["recr_profils"])
        st.session_state["recr_ver"] = st.session_state.get("recr_ver", 0) + 1
        st.rerun()
    b2.caption("Une ligne par profil (ex. « Ingénieur × 2 »). Laissez la durée d'essai vide pour appliquer la durée "
               "statutaire de l'art. 6 (cat. 1-2 : 15 jours · 3-4 : 1 mois · 5-6 : 2 mois · 7-9 : 3 mois · 10-12 : "
               "4 mois ; fonctionnaires détachés et agents mis à disposition : exemptés), ou saisissez la durée voulue "
               "(0,5 = 15 jours). « Essai renouvelé » double la durée (renouvellement unique autorisé).")
    pcfg = {
        "Nombre": st.column_config.NumberColumn(min_value=0, step=1, required=True),
        "Statut": st.column_config.SelectboxColumn(options=list(P["STATUTS"]), required=True),
        "Catégorie": st.column_config.NumberColumn(min_value=1, max_value=12, step=1, required=True),
        "Échelon": st.column_config.SelectboxColumn(options=P["ECHELONS"], required=True,
                                                    help="À l'embauche : échelon A, sauf bonification pour expérience (art. 7)"),
        "Palier": st.column_config.SelectboxColumn(options=P["PALIERS"], required=True),
        "Enfants mineurs": st.column_config.NumberColumn(min_value=0, step=1),
        "Date d'embauche": st.column_config.DateColumn(format="DD/MM/YYYY", required=True),
        "Durée d'essai (mois)": st.column_config.NumberColumn(min_value=0.0, max_value=12.0, step=0.5,
                                                             help="Vide = durée statutaire selon la catégorie"),
        "Essai renouvelé": st.column_config.SelectboxColumn(options=["Non", "Oui"], required=True),
    }
    profils = st.data_editor(st.session_state["recr_profils"], column_config=pcfg, num_rows="dynamic",
                             width="stretch", hide_index=True,
                             key=f"recr_editor_{st.session_state.get('recr_ver', 0)}")
    enregistrer_si_change("recr_profils", profils)

    det, ex_recr = simuler_recrutement(profils, debut, fin, P, avancement=avancement)
    if not ex_recr.empty:
        with st.expander(f"⚠️ {len(ex_recr)} profil(s) non pris en compte"):
            st.dataframe(ex_recr, width="stretch", hide_index=True)
    if det.empty:
        st.info("Aucun coût sur la période : vérifiez les profils et les dates d'embauche.")
    else:
        # Durées d'essai effectivement appliquées
        rappel = []
        for _, p in profils.iterrows():
            try:
                d = p["Durée d'essai (mois)"]
                d = duree_essai_statutaire(int(p["Catégorie"]), str(p["Statut"])) if pd.isna(d) else float(d)
                d = d * 2 if str(p["Essai renouvelé"]) == "Oui" else d
                fin_essai = pd.Timestamp(p["Date d'embauche"]) + pd.DateOffset(days=int(round(d * 30)))
                rappel.append({"Profil / poste": p["Profil / poste"], "Nombre": p["Nombre"],
                               "Durée d'essai appliquée (mois)": d, "Fin d'essai (estimée)": fin_essai.strftime("%d/%m/%Y")})
            except Exception:  # noqa: BLE001
                pass

        total = det["Coût employeur"].sum()
        dernier = det[det["Mois"] == det["Mois"].max()]
        effectif_final = int(dernier["Effectif"].sum())
        cout_croisiere = dernier["Coût employeur"].sum()
        fmt_f = lambda x: f"{x:,.0f} F".replace(",", " ")  # noqa: E731
        kpi_row([
            ("Personnel recruté (fin de période)", str(effectif_final), None),
            ("Coût employeur sur la période", fmt_f(total), None),
            ("Masse brute sur la période", fmt_f(det["Brut"].sum()), None),
            ("Net versé sur la période", fmt_f(det["Net à payer"].sum()), None),
            ("Dont coût pendant l'essai", fmt_f(det["Coût en essai"].sum()), None),
            ("Coût mensuel du dernier mois", fmt_f(cout_croisiere), None),
        ])
        if not res.empty:
            actuel = res["Coût employeur"].sum()
            st.caption(f"Impact sur la masse actuelle (registre de paie, {len(res)} agents) : le coût employeur "
                       f"mensuel passerait de {fmt_f(actuel)} à {fmt_f(actuel + cout_croisiere)} au dernier mois, "
                       f"soit +{cout_croisiere / actuel * 100:.1f} %." if actuel else "")

        par_mois = det.groupby("Mois", as_index=False).agg(
            Effectif=("Effectif", "sum"), **{"Salaire de base": ("Salaire de base", "sum")},
            **{"Indemnités et primes": ("Indemnités et primes", "sum")}, Brut=("Brut", "sum"),
            Retenues=("Retenues", "sum"), **{"Net à payer": ("Net à payer", "sum")},
            **{"Charges patronales": ("Charges patronales", "sum")}, **{"Coût employeur": ("Coût employeur", "sum")},
            **{"Coût en essai": ("Coût en essai", "sum")}, **{"Coût après essai": ("Coût après essai", "sum")})
        par_mois["Coût cumulé"] = par_mois["Coût employeur"].cumsum()

        section_title("COÛT MENSUEL DU PERSONNEL RECRUTÉ")
        long = par_mois.melt(id_vars="Mois", value_vars=["Coût en essai", "Coût après essai"],
                             var_name="Phase", value_name="Coût employeur (FCFA)")
        fig = px.bar(long, x="Mois", y="Coût employeur (FCFA)", color="Phase", barmode="stack",
                     color_discrete_map={"Coût en essai": GOLD, "Coût après essai": NAVY},
                     title="Coût employeur mensuel : période d'essai et après l'essai")
        fig.update_xaxes(dtick="M1", tickformat="%m/%Y")
        st.plotly_chart(plotly_base_layout(fig, height=380), width="stretch")

        money = {c: st.column_config.NumberColumn(format="%d") for c in par_mois.columns if c not in ("Mois", "Effectif")}
        money["Mois"] = st.column_config.DateColumn(format="MM/YYYY")
        st.dataframe(par_mois, width="stretch", hide_index=True, column_config=money)

        section_title("PAR PROFIL SUR LA PÉRIODE")
        par_profil = det.groupby(["Profil / poste", "Catégorie", "Palier"], as_index=False).agg(
            Effectif=("Effectif", "max"), **{"Mois payés": ("Mois", "nunique")}, Brut=("Brut", "sum"),
            **{"Net à payer": ("Net à payer", "sum")}, **{"Charges patronales": ("Charges patronales", "sum")},
            **{"Coût en essai": ("Coût en essai", "sum")}, **{"Coût employeur": ("Coût employeur", "sum")})
        if rappel:
            par_profil = par_profil.merge(pd.DataFrame(rappel)[["Profil / poste", "Durée d'essai appliquée (mois)",
                                                                "Fin d'essai (estimée)"]], on="Profil / poste", how="left")
        par_profil = par_profil.sort_values("Coût employeur", ascending=False)
        st.dataframe(par_profil, width="stretch", hide_index=True,
                     column_config={c: st.column_config.NumberColumn(format="%d") for c in
                                    ("Brut", "Net à payer", "Charges patronales", "Coût en essai", "Coût employeur")})
        with st.expander("Détail mensuel par profil"):
            st.dataframe(det, width="stretch", hide_index=True,
                         column_config={"Mois": st.column_config.DateColumn(format="MM/YYYY")})
        st.download_button("⬇️ Exporter la simulation (Excel)",
                           vers_excel({"Par mois": par_mois, "Par profil": par_profil, "Détail": det,
                                       "Profils saisis": profils}),
                           "simulation_recrutement_aer.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        st.caption("Hypothèses : embauche au 1er du mois ; mois partiellement en essai proratisé ; pas de 13e mois, "
                   "de prime ponctuelle ni d'intérim dans la simulation ; options d'interprétation de l'onglet "
                   "« Paramètres » appliquées.")

render_sidebar_footer(data.generated_on)
