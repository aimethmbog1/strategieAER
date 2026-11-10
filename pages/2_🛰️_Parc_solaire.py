import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from utils.data import NAVY, BLUE, GOLD, CATEGORICAL
from utils.loader import get_data
from utils.ui import PAGE_ICON, inject_base_style, section_title, plotly_base_layout, kpi_row, render_sidebar_footer

st.set_page_config(page_title="Parc solaire — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()

data = get_data()
if data is None:
    st.stop()

st.title("🛰️ Parc solaire — 499 sites")
st.caption("État de fonctionnement des centrales, suivi de la maintenance (arrêts, dépannages, visites) et "
           "dimensionnement des équipes. Pour la carte interactive, ouvrez **« Carte d'électrification »**.")

# =====================================================================
# État de fonctionnement du parc + suivi de la maintenance
# =====================================================================
from utils import maintenance as mt
from utils.personnel import get_effective_roster
from utils.storage import mettre_a_jour, session_ou_stockage

ref_sites = mt.referentiel_sites(data.sites) if data.sites is not None and not data.sites.empty else None
reg = mt.normaliser(session_ou_stockage(mt.REGISTRE, mt.registre_vide))


def _sauver(df, detail):
    df = mt.normaliser(df)
    if mettre_a_jour(mt.REGISTRE, df, detail):
        st.session_state["_mt_ok"] = detail
    st.session_state["_mt_n"] = st.session_state.get("_mt_n", 0) + 1  # réinitialise les formulaires
    st.rerun()


if st.session_state.get("_mt_ok"):
    st.success(f"💾 Enregistré : {st.session_state.pop('_mt_ok')}")

if ref_sites is not None:
    section_title("ÉTAT DE FONCTIONNEMENT DU PARC")
    etat = mt.etat_parc(ref_sites, reg)
    tot = etat[etat["Phase"] == "Total parc"].iloc[0]
    kpi_row([
        ("Centrales fonctionnelles", f"{int(tot['Fonctionnelles'])} / {int(tot['Centrales'])}",
         f"{tot['% centrales fonctionnelles']:.1f} %".replace(".", ",")),
        ("Centrales à l'arrêt", str(int(tot["À l'arrêt"])), None),
        ("Puissance fonctionnelle (kWc)", f"{tot['Puissance fonctionnelle (kWc)']:,.1f}".replace(",", " ").replace(".", ","),
         f"{tot['% puissance fonctionnelle']:.1f} % du parc".replace(".", ",")),
        ("Puissance installée (kWc)", f"{tot['Puissance totale (kWc)']:,.1f}".replace(",", " ").replace(".", ","), None),
    ])
    st.dataframe(etat, width="stretch", hide_index=True,
                 column_config={**{c: st.column_config.NumberColumn(format="localized") for c in
                                   ["Puissance totale (kWc)", "Puissance fonctionnelle (kWc)"]},
                                **{c: st.column_config.ProgressColumn(c, format="%.1f %%", min_value=0, max_value=100)
                                   for c in ["% centrales fonctionnelles", "% puissance fonctionnelle"]}})
    ph = etat[etat["Phase"] != "Total parc"]
    c1, c2 = st.columns(2)
    with c1:
        fig = go.Figure()
        fig.add_bar(name="Fonctionnelles", x=ph["Phase"], y=ph["Fonctionnelles"], marker_color=NAVY)
        fig.add_bar(name="À l'arrêt", x=ph["Phase"], y=ph["À l'arrêt"], marker_color=GOLD)
        fig.update_layout(barmode="stack")
        fig = plotly_base_layout(fig, height=300)
        fig.update_layout(title="Centrales par phase et par état", legend=dict(orientation="h", y=-0.3))
        st.plotly_chart(fig, width="stretch")
    with c2:
        fig = go.Figure()
        fig.add_bar(name="Fonctionnelle", x=ph["Phase"], y=ph["Puissance fonctionnelle (kWc)"], marker_color=NAVY)
        fig.add_bar(name="À l'arrêt", x=ph["Phase"], y=ph["Puissance totale (kWc)"] - ph["Puissance fonctionnelle (kWc)"],
                    marker_color=GOLD)
        fig.update_layout(barmode="stack")
        fig = plotly_base_layout(fig, height=300)
        fig.update_layout(title="Puissance par phase (kWc)", separators=", ", legend=dict(orientation="h", y=-0.3))
        st.plotly_chart(fig, width="stretch")
    st.caption("Une centrale est comptée à l'arrêt tant qu'une panne signalée n'a pas été clôturée par un dépannage. "
               "Pour que ces chiffres reflètent la réalité dès le départ, déclare d'abord dans « Signaler un arrêt » "
               "les centrales actuellement à l'arrêt (plusieurs sites peuvent être sélectionnés à la fois).")

    section_title("SUIVI DE LA MAINTENANCE")
    n = st.session_state.get("_mt_n", 0)
    libelles = dict(zip(ref_sites["site_id"], ref_sites["libelle"]))
    info = ref_sites.set_index("site_id")
    eq_rows, _ = get_effective_roster(data.equipes_rows, data.unassigned)
    equipes = {}
    if eq_rows is not None and not eq_rows.empty:
        for (ant, zone), g in eq_rows.groupby(["Antenne", "Zone"]):
            membres = [str(x) for x in g["Nom"] if str(x).strip() and "MANQUANT" not in str(x)]
            ing = [str(x) for x, r in zip(g["Nom"], g["Rôle"]) if r == "Ingénieur" and "MANQUANT" not in str(x)]
            equipes[f"{ant} — Zone {zone}"] = ing + [m for m in membres if m not in ing]
    equipes["Prestataire / autre"] = []

    def _equipe_chef(prefixe):
        c1, c2 = st.columns(2)
        eq = c1.selectbox("Équipe ayant effectué l'intervention", list(equipes), key=f"{prefixe}_eq_{n}")
        choix_chef = equipes.get(eq, []) + ["Autre (saisir le nom)"]
        chef = c2.selectbox("Chef d'équipe", choix_chef, key=f"{prefixe}_chef_{n}")
        if chef.startswith("Autre"):
            chef = c2.text_input("Nom du chef d'équipe", key=f"{prefixe}_chef_txt_{n}")
        return eq, chef

    def _site_infos(sid):
        r = info.loc[sid]
        return {"site_id": sid, "site": r["Nom du site"], "phase": r["Phase"], "antenne": r["Antenne proposée"],
                "puissance_kwc": float(r["Puissance (kWc)"])}

    t_sig, t_clo, t_vis, t_stat, t_hist = st.tabs(["🚨 Signaler un arrêt", "🔧 Clôturer un dépannage",
                                                   "📋 Enregistrer une visite", "📊 Statistiques", "🗂️ Historique"])

    # ------------------------------------------------------------ signaler
    with t_sig:
        deja = set(mt.pannes_ouvertes(reg)["site_id"])
        dispo = [s for s in ref_sites["site_id"] if s not in deja]
        sel = st.multiselect("Centrale(s) à l'arrêt", dispo, format_func=libelles.get, key=f"sig_sites_{n}",
                             help="Tape quelques lettres du nom pour chercher. Les centrales déjà signalées à l'arrêt "
                                  "n'apparaissent pas.")
        c1, c2 = st.columns(2)
        d = c1.date_input("Date de l'arrêt", value=mt.maintenant().date(), key=f"sig_d_{n}", format="DD/MM/YYYY")
        h = c2.time_input("Heure de l'arrêt", value=mt.maintenant().time(), key=f"sig_h_{n}")
        probs = st.multiselect("Problème(s) constaté(s) ou supposé(s)", mt.PROBLEMES, key=f"sig_p_{n}")
        obs = st.text_area("Observations (qui a signalé, symptômes…)", key=f"sig_o_{n}", height=90)
        if st.button("🚨 Enregistrer l'arrêt", type="primary", disabled=not sel, key=f"sig_btn_{n}"):
            dt = pd.Timestamp.combine(d, h)
            lignes = [{**_site_infos(s), "type": mt.TYPES[0], "statut": "En panne", "date_arret": dt,
                       "problemes": "; ".join(probs), "observations": obs, "saisi_le": pd.Timestamp(mt.maintenant())} for s in sel]
            _sauver(mt.ajouter(reg, lignes), f"arrêt signalé — {len(sel)} centrale(s) : "
                    + ", ".join(info.loc[s, 'Nom du site'] for s in sel[:5]) + ("…" if len(sel) > 5 else ""))

    # ------------------------------------------------------------ clôturer
    with t_clo:
        ouv = mt.pannes_ouvertes(reg)
        if ouv.empty:
            st.info("Aucune centrale n'est actuellement signalée à l'arrêt.")
        else:
            opts = {int(r["id"]): f"{r['site']} ({r['phase']}) — à l'arrêt depuis le {r['date_arret']:%d/%m/%Y %H:%M}"
                    for _, r in ouv.iterrows()}
            pid = st.selectbox("Panne à clôturer", list(opts), format_func=opts.get, key=f"clo_id_{n}")
            p = ouv[ouv["id"] == pid].iloc[0]
            c1, c2, c3 = st.columns(3)
            d = c1.date_input("Date de remise en service", value=mt.maintenant().date(), key=f"clo_d_{n}",
                              min_value=p["date_arret"].date(), format="DD/MM/YYYY")
            h = c2.time_input("Heure de remise en service", value=mt.maintenant().time(), key=f"clo_h_{n}")
            fin = pd.Timestamp.combine(d, h)
            calc = mt.duree_heures(p["date_arret"], fin) or 0.0
            duree = c3.number_input("Temps d'arrêt (heures)", 0.0, 100000.0, float(max(calc, 0.0)), 0.5,
                                    key=f"clo_dur_{n}_{d}_{h}",
                                    help="Calculé entre l'arrêt et la remise en service ; modifiable si besoin.")
            dep = st.date_input("Date du dépannage (passage de l'équipe)", value=d, key=f"clo_dep_{n}", format="DD/MM/YYYY")
            avant = [x for x in str(p["problemes"] or "").split("; ") if x in mt.PROBLEMES]
            probs = st.multiselect("Problème(s) constaté(s) lors du dépannage", mt.PROBLEMES, default=avant, key=f"clo_p_{n}")
            act = st.text_area("Travaux réalisés / pièces remplacées", key=f"clo_a_{n}", height=90)
            eq, chef = _equipe_chef("clo")
            if st.button("🔧 Clôturer le dépannage", type="primary", key=f"clo_btn_{n}"):
                if fin < p["date_arret"]:
                    st.error("La remise en service ne peut pas précéder l'arrêt.")
                else:
                    r2 = reg.copy()
                    i = r2.index[r2["id"] == pid][0]
                    obs = str(p["observations"] or "")
                    r2.loc[i, ["statut", "date_remise", "duree_arret_h", "problemes", "actions", "date_intervention",
                               "equipe", "chef_equipe", "saisi_le"]] = [
                        "Rétablie", fin, round(duree, 1), "; ".join(probs), act, pd.Timestamp(dep), eq, chef, pd.Timestamp(mt.maintenant())]
                    r2.loc[i, "observations"] = obs
                    _sauver(r2, f"dépannage clôturé — {p['site']} ({round(duree, 1)} h d'arrêt)")

    # ------------------------------------------------------------ visite
    with t_vis:
        sel = st.multiselect("Centrale(s) visitée(s)", list(ref_sites["site_id"]), format_func=libelles.get,
                             key=f"vis_sites_{n}")
        c1, c2 = st.columns(2)
        typ = c1.radio("Type de visite", mt.TYPES[1:], horizontal=True, key=f"vis_t_{n}")
        d = c2.date_input("Date de la visite", value=mt.maintenant().date(), key=f"vis_d_{n}", format="DD/MM/YYYY")
        probs = st.multiselect("Problème(s) constaté(s) (facultatif)", mt.PROBLEMES, key=f"vis_p_{n}")
        obs = st.text_area("Observations / travaux réalisés", key=f"vis_o_{n}", height=90)
        eq, chef = _equipe_chef("vis")
        if st.button("📋 Enregistrer la visite", type="primary", disabled=not sel, key=f"vis_btn_{n}"):
            lignes = [{**_site_infos(s), "type": typ, "statut": "Visite", "date_intervention": pd.Timestamp(d),
                       "problemes": "; ".join(probs), "observations": obs, "equipe": eq, "chef_equipe": chef,
                       "saisi_le": pd.Timestamp(mt.maintenant())} for s in sel]
            _sauver(mt.ajouter(reg, lignes), f"{typ.lower()} — {len(sel)} centrale(s), équipe {eq}")

    # ------------------------------------------------------------ statistiques
    with t_stat:
        if reg.empty:
            st.info("Aucune intervention enregistrée pour l'instant.")
        else:
            pan = reg[reg["type"] == mt.TYPES[0]]
            clos = pan[pan["statut"] == "Rétablie"]
            kpi_row([
                ("Arrêts signalés", str(len(pan)), None),
                ("Pannes en cours", str(int((pan["statut"] == "En panne").sum())), None),
                ("Rétablissement moyen",
                 f"{clos['duree_arret_h'].mean():.1f} h".replace(".", ",") if len(clos) else "—", None),
                ("Visites / interventions", str(int(reg["date_intervention"].notna().sum())), None),
                ("Centrales visitées", str(reg.loc[reg["date_intervention"].notna(), "site_id"].nunique()), None),
            ])
            st.markdown("**Arrêts et visites par centrale**")
            spc = mt.stats_par_centrale(reg)
            st.dataframe(spc, width="stretch", hide_index=True,
                         column_config={"Dernière intervention": st.column_config.DateColumn(format="DD/MM/YYYY")})
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Sites visités par équipe**")
                spe = mt.stats_par_equipe(reg)
                st.dataframe(spe, width="stretch", hide_index=True)
                if not spe.empty:
                    fig = px.bar(spe, x="Sites visités", y="Équipe", orientation="h", color_discrete_sequence=[NAVY])
                    st.plotly_chart(plotly_base_layout(fig, height=60 + 28 * len(spe), legend=False), width="stretch")
            with c2:
                st.markdown("**Problèmes les plus fréquents**")
                fp = mt.frequence_problemes(reg)
                if fp.empty:
                    st.caption("Aucun problème renseigné.")
                else:
                    fig = px.bar(fp, x="Occurrences", y="Problème", orientation="h", color_discrete_sequence=[GOLD])
                    fig.update_yaxes(categoryorder="total ascending")
                    st.plotly_chart(plotly_base_layout(fig, height=60 + 28 * len(fp), legend=False), width="stretch")
            top = spc[spc["Arrêts"] > 0].head(15)
            if not top.empty:
                st.markdown("**Centrales les plus souvent à l'arrêt**")
                fig = px.bar(top, x="Centrale", y="Arrêts", color="Durée d'arrêt cumulée (h)",
                             color_continuous_scale="Oranges")
                st.plotly_chart(plotly_base_layout(fig, height=340), width="stretch")

    # ------------------------------------------------------------ historique
    with t_hist:
        if reg.empty:
            st.info("Aucune intervention enregistrée pour l'instant.")
        else:
            vue = reg.sort_values("id", ascending=False).rename(columns={
                "id": "N°", "site": "Centrale", "phase": "Phase", "antenne": "Antenne", "type": "Type", "statut": "Statut",
                "date_arret": "Arrêt", "date_remise": "Remise en service", "duree_arret_h": "Temps d'arrêt (h)",
                "problemes": "Problèmes", "observations": "Observations", "actions": "Travaux / pièces",
                "date_intervention": "Date d'intervention", "equipe": "Équipe", "chef_equipe": "Chef d'équipe"})
            vue = vue.drop(columns=["site_id", "puissance_kwc", "saisi_par", "saisi_le"])
            f = st.text_input("Rechercher (centrale, équipe, problème…)", key="mt_hist_q")
            if f:
                vue = vue[vue.astype(str).apply(lambda s: s.str.contains(f, case=False, regex=False)).any(axis=1)]
            st.dataframe(vue, width="stretch", hide_index=True, height=min(80 + 35 * len(vue), 480),
                         column_config={"Arrêt": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm"),
                                        "Remise en service": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm"),
                                        "Date d'intervention": st.column_config.DateColumn(format="DD/MM/YYYY")})
            st.download_button("⬇️ Exporter l'historique (CSV)", vue.to_csv(index=False, sep=";").encode("utf-8-sig"),
                               "historique_maintenance.csv", "text/csv")
            with st.expander("✏️ Corriger ou supprimer une intervention"):
                cid = st.selectbox("Intervention", reg["id"].tolist()[::-1],
                                   format_func=lambda i: f"N° {i} — " + str(reg.loc[reg['id'] == i, 'site'].iloc[0]) + " — "
                                   + str(reg.loc[reg['id'] == i, 'type'].iloc[0]), key=f"cor_id_{n}")
                r = reg[reg["id"] == cid].iloc[0]
                c1, c2 = st.columns(2)
                statut = c1.selectbox("Statut", mt.STATUTS, index=mt.STATUTS.index(r["statut"]) if r["statut"] in mt.STATUTS else 0,
                                      key=f"cor_s_{n}_{cid}")
                duree = c2.number_input("Temps d'arrêt (heures)", 0.0, 100000.0,
                                        float(r["duree_arret_h"]) if pd.notna(r["duree_arret_h"]) else 0.0, 0.5,
                                        key=f"cor_d_{n}_{cid}")
                probs = st.multiselect("Problèmes", mt.PROBLEMES,
                                       default=[x for x in str(r["problemes"] or "").split("; ") if x in mt.PROBLEMES],
                                       key=f"cor_p_{n}_{cid}")
                obs = st.text_area("Observations", str(r["observations"] or ""), key=f"cor_o_{n}_{cid}", height=70)
                act = st.text_area("Travaux / pièces", str(r["actions"] or ""), key=f"cor_a_{n}_{cid}", height=70)
                chef = st.text_input("Chef d'équipe", str(r["chef_equipe"] or ""), key=f"cor_c_{n}_{cid}")
                b1, b2 = st.columns(2)
                if b1.button("💾 Enregistrer la correction", key=f"cor_ok_{n}"):
                    r2 = reg.copy()
                    i = r2.index[r2["id"] == cid][0]
                    r2.loc[i, ["statut", "duree_arret_h", "problemes", "observations", "actions", "chef_equipe"]] = [
                        statut, round(duree, 1) if r["type"] == mt.TYPES[0] else None, "; ".join(probs), obs, act, chef]
                    _sauver(r2, f"correction de l'intervention n° {cid} ({r['site']})")
                if b2.button("🗑️ Supprimer cette intervention", key=f"cor_del_{n}"):
                    _sauver(reg[reg["id"] != cid], f"suppression de l'intervention n° {cid} ({r['site']})")

st.write("")

# =====================================================================
# Dimensionnement par antenne
# =====================================================================
section_title("DIMENSIONNEMENT DU PERSONNEL PAR ANTENNE")
det = data.antennes_detail
if det is not None and not det.empty:
    kpi_row([
        ("Sites totaux", f"{int(det['Nb sites'].sum()):,}".replace(",", " "), None),
        ("Puissance totale (kWc)", f"{det['Puissance totale (kWc)'].sum():,.1f}".replace(",", " "), None),
        ("Effectif recommandé", f"{int(det['Effectif total'].sum()):,}", None),
        ("Antennes", str(len(det)), None),
    ])
    st.dataframe(det, width="stretch", hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        fig = px.bar(det, x="Antenne", y="Nb sites", color_discrete_sequence=[BLUE], title="Sites par antenne")
        fig = plotly_base_layout(fig, legend=False)
        st.plotly_chart(fig, width="stretch")
    with c2:
        fig = px.pie(det, names="Antenne", values="Puissance totale (kWc)", hole=0.35,
                     color_discrete_sequence=CATEGORICAL, title="Puissance installée par antenne")
        fig.update_traces(textinfo="percent")
        fig = plotly_base_layout(fig)
        st.plotly_chart(fig, width="stretch")

    c3, c4 = st.columns(2)
    with c3:
        fig = go.Figure()
        for col, color in zip(["Chef + admin", "Ingénieurs techniques", "Agents communautaires"],
                               [NAVY, BLUE, GOLD]):
            fig.add_bar(name=col, x=det["Antenne"], y=det[col], marker_color=color)
        fig.update_layout(barmode="stack")
        fig = plotly_base_layout(fig)
        fig.update_layout(title="Effectif recommandé, par fonction")
        st.plotly_chart(fig, width="stretch")
    with c4:
        fig = px.bar(det.sort_values("Sites par agent"), x="Antenne", y="Sites par agent",
                     color_discrete_sequence=[GOLD], title="Charge relative (sites / agent)")
        fig = plotly_base_layout(fig, legend=False)
        st.plotly_chart(fig, width="stretch")
else:
    st.warning("Feuille « Antennes — Détail solaire » introuvable ou vide.")

st.write("")

# =====================================================================
# Liste des 499 sites — filtrable + carte
# =====================================================================
section_title("LISTE DES SITES — FILTRES & TABLEAU")
sites = data.sites
if sites is not None and not sites.empty:
    fc1, fc2, fc3, fc4 = st.columns(4)
    antennes = sorted(sites["Antenne proposée"].dropna().unique())
    regions = sorted(sites["Région"].dropna().unique())
    phases = sorted(sites["Phase"].dropna().unique())
    f_antenne = fc1.multiselect("Antenne", antennes, default=[])
    f_region = fc2.multiselect("Région", regions, default=[])
    f_phase = fc3.multiselect("Phase", phases, default=[])
    f_search = fc4.text_input("Rechercher un site")

    view = sites.copy()
    if f_antenne:
        view = view[view["Antenne proposée"].isin(f_antenne)]
    if f_region:
        view = view[view["Région"].isin(f_region)]
    if f_phase:
        view = view[view["Phase"].isin(f_phase)]
    if f_search:
        view = view[view["Nom du site"].astype(str).str.contains(f_search, case=False, na=False)]

    st.caption(f"{len(view)} site(s) affiché(s) sur {len(sites)}")

    tab_table, tab_charts = st.tabs(["📋 Tableau", "📊 Répartition"])
    with tab_table:
        st.dataframe(view, width="stretch", hide_index=True, height=480)
        st.download_button("⬇️ Télécharger cette sélection (CSV)", view.to_csv(index=False).encode("utf-8"),
                            "sites_filtrés.csv", "text/csv")
    with tab_charts:
        cc1, cc2 = st.columns(2)
        with cc1:
            by_antenne = view.groupby("Antenne proposée", as_index=False)["Puissance (kWc)"].sum()
            fig = px.bar(by_antenne.sort_values("Puissance (kWc)", ascending=False),
                         x="Antenne proposée", y="Puissance (kWc)", color_discrete_sequence=[NAVY])
            fig = plotly_base_layout(fig, legend=False)
            fig.update_layout(title="Puissance (kWc) — sélection courante")
            st.plotly_chart(fig, width="stretch")
        with cc2:
            by_region = view.groupby("Région", as_index=False).size()
            fig = px.bar(by_region.sort_values("size", ascending=False),
                         x="Région", y="size", color_discrete_sequence=[GOLD])
            fig = plotly_base_layout(fig, legend=False)
            fig.update_layout(title="Nombre de sites par région — sélection courante", yaxis_title="Sites")
            st.plotly_chart(fig, width="stretch")
else:
    st.warning("Feuille « Données sites » introuvable ou vide.")

render_sidebar_footer(data.generated_on)
