import html
import io

import pandas as pd
import plotly.express as px
import streamlit as st

from utils import gmao_core as gc
from utils import gmao_indicateurs as gi
from utils import gmao_suivi as gs
from utils import maintenance as mt
from utils.auth import peut_modifier
from utils.loader import get_data
from utils.ui import PAGE_ICON, inject_base_style, kpi_row, plotly_base_layout, render_sidebar_footer, section_title

st.set_page_config(page_title="Suivi de la maintenance des centrales — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()
data = get_data()
if data is None or data.sites is None or data.sites.empty:
    st.stop()

COULEURS = {gi.H24: "#16A34A", gi.A_VIDE: "#0891B2", gi.AVANT_18H: "#EA580C", gi.APRES_18H: "#D97706",
            gi.PARTIEL_AUTRE: "#CA8A04", gi.ARRET: "#DC2626", gi.NON_RENSEIGNE: "#9CA3AF"}
COULEURS_GROUPE = {"En service H24": "#16A34A", "Service partiel": "#D97706", "À l'arrêt": "#DC2626",
                   gi.NON_MES: "#9CA3AF", gi.NON_RENSEIGNE: "#D1D5DB"}
VERT, ORANGE, ROUGE = "#0F766E", "#C2410C", "#B91C1C"


def n(x, dec: int = 0, suffixe: str = "") -> str:
    """Nombre au format français (espace des milliers, virgule décimale) ; « — » si absent."""
    if x is None or pd.isna(x):
        return "—"
    return f"{x:,.{dec}f}".replace(",", " ").replace(".", ",") + suffixe


def fig_(fig, hauteur=330, **kw):
    fig = plotly_base_layout(fig, height=hauteur, **kw)
    fig.update_layout(separators=", ", legend=dict(orientation="h", y=-0.28), margin=dict(t=30))
    return fig


st.title("🛠️ Suivi de la maintenance des centrales")
st.caption("Pilotage de la maintenance du parc à partir des données déjà présentes dans le GMAO : journaux de "
           "maintenance importés, bons d'intervention, inspections, affectations par zone et supervision.")
st.markdown("""<style>
.sm-t{width:100%;border-collapse:collapse;font-size:.9rem}.sm-t th{text-align:left;color:#475569;font-weight:600;padding:.35rem .5rem;border-bottom:1px solid #E2E8F0}
.sm-t td{padding:.4rem .5rem;border-bottom:1px solid #F1F5F9;vertical-align:top}.sm-t td b{font-size:1.05rem}
.sm-t small{display:block;color:#64748B;font-size:.76rem}.sm-p{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:4px}
.sm-b{display:flex;height:12px;border-radius:3px;overflow:hidden;min-width:180px;background:#E5E7EB}
</style>""", unsafe_allow_html=True)

# ----------------------------------------------------------------------------- données
auj = gi.maintenant_douala()
ref = mt.referentiel_sites(data.sites)
bi = gc.table("gmao_bi")
sites, absents_ref = gs.sites_suivis(ref, bi)
f0 = gs.fiches(auj, bi)
poids, delais = gs.poids(), gs.delais()
seuil_recidive = int(gs.reglage("seuil_recidive", gi.SEUIL_RECIDIVE_DEFAUT))
cible = gs.reglage("puissance_cible", None)

if f0.empty and (sites["etat"] == gi.NON_RENSEIGNE).all():
    st.info("Aucun journal de maintenance n'est chargé : importe-les dans « GMAO — Maintenance → Paramètres & imports ».")
    render_sidebar_footer("")
    st.stop()

t_vue, t_par = st.tabs(["📊 Vue d'ensemble", "⚙️ Paramètres"])

# ============================================================================= VUE D'ENSEMBLE
with t_vue:
    with st.expander("🔎 Filtres", expanded=False):
        c = st.columns(4)
        f_src = c[0].multiselect("Source", sorted(f0["source"].dropna().unique()), key="sm_src")
        f_reg = c[1].multiselect("Région", sorted(sites["region"].dropna().unique()), key="sm_reg")
        f_zone = c[2].multiselect("Zone", sorted(sites["zone"].dropna().unique()), key="sm_zone")
        f_ph = c[3].multiselect("Phase", sorted(sites["phase"].dropna().unique()), key="sm_ph")
        c = st.columns(4)
        f_cat = c[0].multiselect("Catégorie", sorted(f0["categorie"].dropna().unique()), key="sm_cat")
        f_prio = c[1].multiselect("Priorité", gi.PRIORITES, key="sm_prio")
        f_stat = c[2].selectbox("Statut des fiches", ["Tous", "Ouvert", "Clôturé"], key="sm_stat")
        periode = c[3].date_input("Période (date de constat)", value=(), key="sm_per", format="DD/MM/YYYY")
    s = sites
    for col, val in (("region", f_reg), ("zone", f_zone), ("phase", f_ph)):
        if val:
            s = s[s[col].isin(val)]
    debut, fin = (periode[0], periode[1]) if isinstance(periode, tuple) and len(periode) == 2 else (None, None)
    f, sans_date = gi.filtrer_fiches(f0, sources=f_src, regions=f_reg, phases=f_ph, categories=f_cat, priorites=f_prio,
                                     statut=None if f_stat == "Tous" else f_stat,
                                     sites=set(s["cle_site"]) if f_zone else None, debut=debut, fin=fin)
    if debut is not None and sans_date:
        st.warning(f"{sans_date} fiche(s) sans date de constat ne peuvent pas être situées dans la période : elles "
                   "sont écartées des indicateurs ci-dessous tant que le filtre de période est actif.")

    # ---- état de fonctionnement
    section_title("ÉTAT DE FONCTIONNEMENT DES CENTRALES — PHASES 1 ET 2")
    te = gi.tableau_etats(s)
    etats_aff = [e for e in gi.ETATS_DETAILLES + [gi.NON_RENSEIGNE] if te.loc[te["etat"] == e, "nb"].sum() > 0
                 or e in (gi.H24, gi.A_VIDE, gi.AVANT_18H, gi.APRES_18H, gi.ARRET)]
    if te.empty or te["sites_phase"].max() == 0:
        st.info("Aucune centrale de Phase 1 ou 2 dans la sélection.")
    else:
        lignes = ["<table class='sm-t'><tr><th>Phase</th><th>Nb</th>" + "".join(
            f"<th><span class='sm-p' style='background:{COULEURS[e]}'></span>{html.escape(e)}</th>" for e in etats_aff)
            + "<th>Répartition</th></tr>"]
        for ph in list(dict.fromkeys(te["phase"])):
            g_ = te[te["phase"] == ph].set_index("etat")
            barre = "".join(f"<div style='width:{g_.at[e, 'pct']:.2f}%;background:{COULEURS[e]}'></div>" for e in etats_aff)
            lignes.append(f"<tr><td>{'<b>Total</b>' if ph == 'Total' else html.escape(str(ph))}</td><td>{int(g_['sites_phase'].iloc[0])}</td>"
                          + "".join(f"<td><b>{int(g_.at[e, 'nb'])}</b><small>{n(g_.at[e, 'pct'])} % · {n(g_.at[e, 'kwc'])} kWc</small></td>"
                                    for e in etats_aff) + f"<td><div class='sm-b'>{barre}</div></td></tr>")
        st.markdown("".join(lignes) + "</table>", unsafe_allow_html=True)
        st.caption("Les sites de Phase 3 (non mis en service) ne sont pas comptés. Source : dernier état de chaque "
                   "centrale dans les journaux importés ; un bon d'intervention correctif ouvert « centrale à l'arrêt » "
                   "impose l'état « À l'arrêt ». « Fonctionne à vide » n'apparaît que s'il a été saisi : les journaux "
                   "ne le distinguent pas.")
        c1, c2 = st.columns([1, 3])
        e_sel = c1.selectbox("Voir la liste des centrales", etats_aff, index=None, key="sm_liste",
                             placeholder="Choisir un état…")
        if e_sel:
            lst = s[(s["etat"] == e_sel) & s["phase"].isin(["Phase 1", "Phase 2"])]
            c2.dataframe(lst[["site", "phase", "region", "zone", "kwc", "cause", "responsable"]].rename(columns={
                "site": "Centrale", "phase": "Phase", "region": "Région", "zone": "Zone", "kwc": "kWc",
                "cause": "Cause déclarée", "responsable": "Responsable"}), hide_index=True, width="stretch", height=260)

    # ---- réhabilitation
    st.info("**Réhabilitation — à compléter.** Le programme de chaque site (Exclue, Réhabilitation PH1, PH2, PH2+, PH3), "
            "les centrales réhabilitées, mises en exploitation, et les kWh de batteries installés ne figurent dans "
            "aucune donnée de l'application. Ce bloc sera alimenté par le référentiel des sites (lot « Parc de sites »).")

    # ---- priorités d'intervention
    arrets = gs.arrets_connus(f0, bi)
    visites = gs.visites_connues(f0, bi)
    seuil_sup = int(gs.reglage("supervision_seuil_j", 2))
    deconn = gs.supervision_deconnectee(seuil_sup)
    sc = gi.scores_sites(s, f0, arrets, visites, auj, poids, supervision={k: "déconnectée" for k in deconn})
    pr = gi.priorites_intervention(s, f0, sc, visites, auj, poids)
    section_title("PRIORITÉS D'INTERVENTION")
    kpi_row([
        ("Sites très exposés", n(pr["tres_exposes"]),
         f"{poids['seuil_tres_expose']} points ou plus, sur {pr['en_service_h24']} en service H24"),
        ("À remettre en service", n(pr["a_remettre"]), f"à l'arrêt ou partiels ; {pr['a_remettre_sans_fiche']} sans fiche"),
        ("dont Phase 1 à l'arrêt", n(pr["phase1_arret"]), "réhabilitation : à confirmer"),
        (f"Sans visite depuis {poids['sans_visite_mois']} mois", n(pr["sans_visite"]),
         f"sur {pr['en_service']} en service ; {pr['jamais_visites']} jamais"),
        ("Urgentes / critiques en retard", n(pr["urgents_critiques_hors_delai"]), "fiches ouvertes hors délai"),
    ])
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Sites en service les plus exposés à un arrêt**")
        if sc.empty:
            st.info("Aucun site en service dans la sélection.")
        else:
            st.dataframe(sc.head(50)[["Site", "Région", "kWc", "Points", "Motifs", "Responsable"]], hide_index=True,
                         width="stretch", height=330,
                         column_config={"Points": st.column_config.ProgressColumn("Points", format="%d", min_value=0,
                                                                                  max_value=int(max(sc["Points"].max(), 1))),
                                        "Motifs": st.column_config.TextColumn(width="large")})
        st.caption(
            f"Classement d'aide au tri, pas une mesure. Fiches ouvertes depuis moins de {poids['fenetre_mois']} mois : "
            f"URGENT {poids['fiche']['URGENT']}, CRITIQUE {poids['fiche']['CRITIQUE']}, MAJEUR {poids['fiche']['MAJEUR']}, "
            f"autres {poids['fiche']['autre']} (plafond {poids['plafond_fiches']}) ; arrêts : {poids['arret']} chacun "
            f"(plafond {poids['plafond_arrets']}) ; aucune visite depuis {poids['sans_visite_mois']} mois : "
            f"{poids['sans_visite']} ; supervision déconnectée : {poids['supervision']['déconnectée']}. Les signaux de "
            "performance (taux de service, batterie vide, écart entre cellules, rendement du stockage) et la supervision "
            "« défaillante » ne sont pas comptés : ces mesures n'existent pas encore dans l'application.")
    with c2:
        st.markdown("**Sites à l'arrêt ou en service partiel à remettre en service**")
        rem = gi.a_remettre_en_service(s, f0)
        if rem.empty:
            st.success("Aucun site à l'arrêt ou en service partiel dans la sélection.")
        else:
            st.dataframe(rem[["Site", "Phase", "Région", "kWc", "État", "Cause déclarée", "Suivi"]], hide_index=True,
                         width="stretch", height=330)
        st.caption("Toutes les centrales de Phases 1 et 2 à l'arrêt ou en service partiel sont listées : sans le "
                   "programme de réhabilitation, les sites de Phase 1 en attente ne peuvent pas être mis à part. "
                   "Suivi : fiches ouvertes et âge de la plus ancienne.")

    # ---- interruptions peut-être non signalées
    ins = gi.interruptions_non_signalees(s, f0, auj, int(gs.reglage("interruption_jours", 90)), deconn)
    section_title("INTERRUPTIONS PEUT-ÊTRE NON SIGNALÉES")
    if ins.empty:
        st.success("Aucun indice d'interruption sur les sites déclarés en service.")
    else:
        st.warning(f"{ins['cle_site'].nunique()} site(s) déclaré(s) en service présentent un indice d'arrêt : à vérifier "
                   "auprès du responsable de zone, puis à corriger (état du site ou clôture de la fiche).")
        st.dataframe(ins[["Site", "Région", "État déclaré", "Indice", "Date de l'indice"]], hide_index=True, width="stretch",
                     column_config={"Date de l'indice": st.column_config.DateColumn(format="DD/MM/YYYY"),
                                    "Indice": st.column_config.TextColumn(width="large")})
    st.caption("Indices recherchés : une fiche encore ouverte a constaté le site à l'arrêt il y a moins de "
               f"{int(gs.reglage('interruption_jours', 90))} jours ; la supervision n'a plus de donnée depuis plus de "
               f"{seuil_sup} jours (pour les seules centrales dont des mesures de supervision sont importées).")

    # ---- puissance du parc
    pu = gi.puissance_parc(s, cible)
    section_title("PUISSANCE DU PARC")
    kpi_row([
        ("Puissance cible", n(pu["cible"], suffixe=" kWc"), "modifiable dans Paramètres" if cible else "= puissance installée (par défaut)"),
        ("Puissance installée", n(pu["installee"], suffixe=" kWc"), f"{len(s)} sites"),
        ("En service", n(pu["en_service"], suffixe=" kWc"), f"dont {n(pu['partiel'])} kWc en service partiel"),
        ("Atteinte de la cible", n(pu["pct_cible"], suffixe=" %"), f"écart : {n(pu['ecart_cible'])} kWc"),
        ("À l'arrêt", n(pu["arret"], suffixe=" kWc"), f"{pu['sites_arret']} sites"),
        ("Non mise en service", n(pu["non_mes"], suffixe=" kWc"), f"{pu['sites_non_mes']} sites"),
    ])
    pp = pu["par_phase"]
    st.dataframe(pp.drop(columns=[c_ for c_ in ["Non renseignée (kWc)"] if pp[c_].sum() == 0]), hide_index=True, width="stretch",
                 column_config={**{c_: st.column_config.NumberColumn(format="%.0f") for c_ in pp.columns if "kWc" in c_},
                                "% exploité": st.column_config.ProgressColumn("% exploité", format="%.0f %%", min_value=0, max_value=100)})
    st.caption("« En service » = en service H24 + service partiel. « % exploité » = part de la puissance mise en "
               "service qui fonctionne. Le détail par programme de réhabilitation est à compléter (voir plus haut).")

    # ---- indicateurs de maintenance
    k = gi.indicateurs_maintenance(f, seuil_recidive)
    m = k["mttr"]
    gr = s["etat"].map(gi.GROUPE)
    mes = int(gr.isin(["En service H24", "Service partiel", "À l'arrêt"]).sum())
    vis_p = visites if debut is None else visites[(visites["date"] >= pd.Timestamp(debut)) & (visites["date"] <= pd.Timestamp(fin))]
    vis_p = vis_p[vis_p["cle_site"].isin(set(s["cle_site"]))]
    arr_p = arrets if debut is None else arrets[(arrets["date"] >= pd.Timestamp(debut)) & (arrets["date"] <= pd.Timestamp(fin))]
    arr_p = arr_p[arr_p["cle_site"].isin(set(s["cle_site"]))]
    section_title("MAINTENANCE")
    kpi_row([
        ("Sites en service H24", f"{int((gr == 'En service H24').sum())} / {mes}", f"{pu['sites_non_mes']} non mis en service"),
        ("Sites à l'arrêt", n(pu["sites_arret"]), f"{n(pu['arret'])} kWc indisponibles"),
        ("Défauts enregistrés", n(k["enregistrees"]), f"{k['sites_touches']} sites touchés"),
        ("Backlog ouvert", n(k["backlog"]), f"âge médian {n(k['age_median_j'])} j"),
        ("Backlog hors délai", n(k["pct_hors_delai"], suffixe=" %"), f"{k['hors_delai']} fiches ; {k['ouvertes_sans_echeance']} sans échéance"),
        ("Urgents / critiques ouverts", n(k["urgents_critiques_ouverts"]), f"dont {k['urgents_critiques_hors_delai']} hors délai"),
        ("Taux de clôture", n(k["taux_cloture"], suffixe=" %"), f"{k['cloturees']} fiches clôturées"),
    ])
    kpi_row([
        ("Respect du délai", n(k["respect_delai"], suffixe=" %"), f"sur {k['respect_delai_base']} clôtures datées"),
        ("MTTR médian", n(m["mttr"], suffixe=" j"), f"sur {m['retenues']} fiches ; {m['meme_jour']} clôtures le jour même écartées"),
        ("Sites récidivistes", n(k["recidivistes"]), f"{seuil_recidive} défauts ou plus"),
        ("Constats site à l'arrêt", n(k["pct_constats_arret"], suffixe=" %"), f"{k['constats_arret']} interventions"),
        ("Centrales visitées", n(vis_p["cle_site"].nunique()), f"{len(vis_p)} passages · {n(100 * vis_p['cle_site'].nunique() / mes if mes else None)} % du parc en exploitation"),
        ("Arrêts sur la période", n(len(arr_p)), f"{arr_p['cle_site'].nunique()} sites concernés"),
        ("Batteries remplacées / affectées", f"{n(k['batteries_remplacees'])} / {n(k['batteries_affectees'])}", f"{n(k['pct_batteries'])} % couvert"),
    ])
    st.caption(
        f"Hors délai : fiche ouverte dont l'échéance est dépassée. Échéance = date de constat + délai de la priorité "
        f"(URGENT {n(delais['URGENT'])} j, CRITIQUE {n(delais['CRITIQUE'])} j, MAJEUR {n(delais['MAJEUR'])} j, MINEUR "
        f"{n(delais['MINEUR'])} j) ; quand le délai d'une priorité n'est pas paramétré (« — »), la fiche garde le nombre "
        f"de jours prévu du journal, et n'a pas d'échéance s'il manque. MTTR : médiane constat → clôture, sur les fiches "
        f"clôturées aux dates valides ; {m['sans_date']} sans date et {m['incoherentes']} à la clôture antérieure au "
        f"constat sont ignorées ; en gardant les {m['meme_jour']} clôtures du jour même, la médiane serait de "
        f"{n(m['mttr_avec_meme_jour'])} j. Passages : inspections, constats de défaut et interventions terminées "
        "(un par site et par jour). Arrêts : constats « site à l'arrêt » et bons d'intervention avec arrêt.")

    # ---- graphiques
    if f.empty:
        st.info("Aucune fiche ne correspond aux filtres.")
    else:
        c1, c2, c3 = st.columns(3)
        with c1:
            d = gi.defauts_par_mois(f)
            fig = px.bar(d, x="Mois", y=["Clôturés", "Ouverts"], title="Défauts déclarés par mois",
                         color_discrete_map={"Clôturés": VERT, "Ouverts": ORANGE}, labels={"value": "Défauts", "variable": ""})
            st.plotly_chart(fig_(fig), width="stretch")
            if k["sans_date_constat"]:
                st.caption(f"{k['sans_date_constat']} fiche(s) sans date de constat ne figurent pas sur ce graphique.")
        with c2:
            e = gi.etat_par_region(s)
            fig = px.bar(e, x="Région", y=[c_ for c_ in gi.GROUPES if c_ in e.columns], title="État du parc par région",
                         color_discrete_map=COULEURS_GROUPE, labels={"value": "Centrales", "variable": ""})
            st.plotly_chart(fig_(fig), width="stretch")
        with c3:
            r = gi.repartition(f, "categorie", "Catégorie").sort_values("Défauts")
            fig = px.bar(r, y="Catégorie", x="Défauts", orientation="h", title="Défauts par catégorie",
                         color_discrete_sequence=["#2563EB"])
            st.plotly_chart(fig_(fig, legend=False), width="stretch")
        c1, c2, c3 = st.columns(3)
        with c1:
            b = gi.backlog_par_anciennete(f)
            fig = px.bar(b, x="Âge", y=["Dans le délai", "Hors délai"], title="Backlog : ancienneté et respect du délai",
                         color_discrete_map={"Dans le délai": VERT, "Hors délai": ROUGE}, labels={"value": "Fiches ouvertes", "variable": ""})
            st.plotly_chart(fig_(fig), width="stretch")
            st.caption("« Dans le délai » comprend les fiches sans échéance (délai non paramétré).")
        with c2:
            r = gi.repartition(f, "region", "Région")
            fig = px.bar(r, x="Région", y=["Clôturés", "Ouverts"], title="Défauts par région (ouverts / clôturés)",
                         color_discrete_map={"Clôturés": VERT, "Ouverts": ORANGE}, labels={"value": "Défauts", "variable": ""})
            st.plotly_chart(fig_(fig), width="stretch")
        with c3:
            z = f.assign(zone=f["cle_site"].map(sites.drop_duplicates("cle_site").set_index("cle_site")["zone"]))
            r = gi.repartition(z[z["ouvert"]], "zone", "Zone").sort_values("Zone").rename(columns={"Hors délai": "dont hors délai"})
            fig = px.bar(r, x="Zone", y=["Ouverts", "dont hors délai"], barmode="group", title="Défauts ouverts par zone de maintenance",
                         color_discrete_map={"Ouverts": ORANGE, "dont hors délai": ROUGE}, labels={"value": "Fiches", "variable": ""})
            st.plotly_chart(fig_(fig), width="stretch")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Top 10 des sites les plus défaillants**")
            st.dataframe(gi.top_sites(f, sites, 10), hide_index=True, width="stretch")
        with c2:
            st.markdown("**Matériel : affecté, remplacé, reste à fournir (en pièces)**")
            mat = gi.materiel_affecte_remplace(f)
            st.dataframe(mat.head(15), hide_index=True, width="stretch",
                         column_config={c_: st.column_config.NumberColumn(format="%.0f") for c_ in ("Affecté", "Remplacé", "Reste à fournir")})
            st.caption("Câbles et lignes (en mètres) exclus : unités non comparables aux pièces."
                       + (f" {k['materiel_non_renseigne']} fiche(s) n'indiquent pas le matériel : elles sont regroupées "
                          "sous « Non renseigné » et sont à corriger." if k["materiel_non_renseigne"] else ""))
        buf = io.BytesIO()
        with pd.ExcelWriter(buf) as xl:
            f.drop(columns=["cle_site", "mois"]).to_excel(xl, sheet_name="Fiches", index=False)
            sc.drop(columns=["cle_site"]).to_excel(xl, sheet_name="Sites exposés", index=False) if len(sc) else None
            gi.a_remettre_en_service(s, f0).drop(columns=["cle_site"]).to_excel(xl, sheet_name="À remettre en service", index=False)
        st.download_button("⬇️ Exporter les fiches et les priorités (Excel)", buf.getvalue(), "suivi_maintenance.xlsx", key="sm_dl")

    if absents_ref:
        with st.expander(f"🧪 Qualité des données : {len(absents_ref)} centrale(s) des journaux absentes du référentiel"):
            st.caption("Ces noms ne se retrouvent pas tels quels dans le référentiel des sites (orthographe différente "
                       "ou site manquant). Elles sont comptées ici d'après les journaux, mais restent à rapprocher.")
            st.write(", ".join(absents_ref))
    st.caption("Les onglets Parc de sites, Backlog et nouvelle fiche, Arrêts et disponibilité, Visites arrivent aux "
               "lots suivants ; Stocks et Équipes étendront les modules du GMAO.")

# ============================================================================= PARAMÈTRES
with t_par:
    edition = peut_modifier()
    st.caption("Délais, poids et seuils utilisés par les calculs. Ils sont enregistrés dans la base et s'appliquent "
               "à tous les utilisateurs." + ("" if edition else " Lecture seule pour votre profil."))
    if st.session_state.get("_sm_ok"):
        st.success("💾 " + st.session_state.pop("_sm_ok"))
    with st.form("sm_param"):
        st.markdown("**Délai de résolution par priorité (jours)** — 0 ou vide = non défini : la fiche garde alors le "
                    "nombre de jours prévu du journal.")
        c = st.columns(4)
        nd = {p: c[i].number_input(p, min_value=0, step=1, value=delais[p], key=f"sm_d_{p}", disabled=not edition,
                                   help="À compléter" if delais[p] is None else None)
              for i, p in enumerate(["URGENT", "CRITIQUE", "MAJEUR", "MINEUR"])}
        st.markdown("**Score d'exposition à l'arrêt**")
        c = st.columns(6)
        pf = {p: c[i].number_input(f"Fiche {p}", 0, 50, int(poids["fiche"][p]), key=f"sm_pf_{p}", disabled=not edition)
              for i, p in enumerate(["URGENT", "CRITIQUE", "MAJEUR", "autre"])}
        plaf_f = c[4].number_input("Plafond fiches", 0, 200, int(poids["plafond_fiches"]), key="sm_plf", disabled=not edition)
        fen = c[5].number_input("Fenêtre (mois)", 1, 60, int(poids["fenetre_mois"]), key="sm_fen", disabled=not edition)
        c = st.columns(6)
        p_arr = c[0].number_input("Par arrêt", 0, 50, int(poids["arret"]), key="sm_pa", disabled=not edition)
        plaf_a = c[1].number_input("Plafond arrêts", 0, 200, int(poids["plafond_arrets"]), key="sm_pla", disabled=not edition)
        p_vis = c[2].number_input("Sans visite", 0, 50, int(poids["sans_visite"]), key="sm_pv", disabled=not edition)
        m_vis = c[3].number_input("Sans visite depuis (mois)", 1, 36, int(poids["sans_visite_mois"]), key="sm_mv", disabled=not edition)
        p_dec = c[4].number_input("Supervision déconnectée", 0, 50, int(poids["supervision"]["déconnectée"]), key="sm_pd", disabled=not edition)
        p_def = c[5].number_input("Supervision défaillante", 0, 50, int(poids["supervision"]["défaillante"]), key="sm_pdf", disabled=not edition)
        c = st.columns(5)
        sig = {kk: c[i].number_input(gi.LIBELLES_SIGNAUX[kk].capitalize(), 0, 50, int(poids["signaux"][kk]), key=f"sm_s_{kk}",
                                     disabled=not edition) for i, kk in enumerate(gi.LIBELLES_SIGNAUX)}
        seuil_te = c[4].number_input("Seuil « très exposé » (points)", 1, 200, int(poids["seuil_tres_expose"]), key="sm_te", disabled=not edition)
        st.markdown("**Autres réglages**")
        c = st.columns(4)
        n_rec = c[0].number_input("Site récidiviste à partir de (défauts)", 2, 100, seuil_recidive, key="sm_rec", disabled=not edition)
        n_cible = c[1].number_input("Puissance cible (kWc) — 0 = puissance installée", 0.0, 10**7 * 1.0, float(cible or 0), step=100.0,
                                    key="sm_cible", disabled=not edition)
        n_int = c[2].number_input("Indice d'interruption : constat d'arrêt de moins de (jours)", 1, 720,
                                  int(gs.reglage("interruption_jours", 90)), key="sm_int", disabled=not edition)
        n_sup = c[3].number_input("Supervision déconnectée au-delà de (jours)", 1, 90, seuil_sup, key="sm_sup", disabled=not edition)
        if st.form_submit_button("💾 Enregistrer les paramètres", type="primary", disabled=not edition):
            gs.enregistrer_reglages({
                "delais": {p: (int(v) if v else None) for p, v in nd.items()},
                "poids": {"fiche": {p: int(v) for p, v in pf.items()}, "plafond_fiches": int(plaf_f), "fenetre_mois": int(fen),
                          "arret": int(p_arr), "plafond_arrets": int(plaf_a), "sans_visite": int(p_vis),
                          "sans_visite_mois": int(m_vis), "signaux": {kk: int(v) for kk, v in sig.items()},
                          "supervision": {"déconnectée": int(p_dec), "défaillante": int(p_def)},
                          "seuil_tres_expose": int(seuil_te)},
                "seuil_recidive": int(n_rec), "puissance_cible": float(n_cible) or None,
                "interruption_jours": int(n_int), "supervision_seuil_j": int(n_sup)})
            st.session_state["_sm_ok"] = "Paramètres enregistrés."
            st.rerun()
    st.caption("Valeurs de départ : URGENT 2 jours et CRITIQUE 7 jours (relevés sur le prototype) ; MAJEUR et MINEUR "
               "restent à compléter. Les poids du score sont ceux affichés par le prototype.")

render_sidebar_footer("")
