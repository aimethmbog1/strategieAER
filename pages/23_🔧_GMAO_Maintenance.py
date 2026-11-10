import io

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from utils import gmao as gj
from utils import gmao_core as gc
from utils import gmao_ui
from utils import maintenance as mt
from utils.data import BLUE, GOLD, GREY, NAVY, RED
from utils.loader import get_data
from utils.personnel import get_effective_roster
from utils.ui import PAGE_ICON, inject_base_style, kpi_row, plotly_base_layout, render_sidebar_footer, section_title

st.set_page_config(page_title="GMAO — Maintenance des centrales — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()
data = get_data()
if data is None or data.sites is None or data.sites.empty:
    st.stop()

# ----------------------------------------------------------------------------- style des tuiles
TUILES = [  # (clé module, libellé, icône, couleur)
    ("di", "Créer une DI", "🚨", "#C0392B"), ("bi", "Bons d'intervention", "🧾", "#E67E22"),
    ("equipements", "Arborescence", "🌳", "#27AE60"), ("planning", "Préventif & planning", "🗓️", "#2E86C1"),
    ("stocks", "Stocks", "📦", "#8E44AD"), ("achats", "Achats", "🛒", "#16A085"),
    ("budgets", "Budgets", "💰", "#D4AC0D"), ("ressources", "Ressources", "👷", "#5D6D7E"),
    ("analyses", "Analyses", "📊", "#1F3A5F"), ("terrain", "Mode terrain", "📱", "#117A65"),
]
css = "".join(f".st-key-tuile_{k} button{{background:{c};color:#fff;border:0;min-height:92px;border-radius:10px;"
              f"font-weight:600;font-size:1.02rem;white-space:pre-line}}.st-key-tuile_{k} button:hover{{filter:brightness(1.1);"
              f"color:#fff;border:0}}" for k, _, _, c in TUILES)
css += (".gm-compteur{border-radius:8px;padding:10px 4px;text-align:center;color:#fff;font-weight:600;font-size:.85rem;white-space:nowrap;overflow:hidden}"
        ".gm-compteur b{display:block;font-size:1.6rem}")
st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

MODULES = {"accueil": "🏠 Accueil", "equipements": "🌳 Équipements", "di": "🚨 Demandes (DI)",
           "bi": "🧾 Bons d'intervention (BI)", "planning": "🗓️ Préventif & planning", "stocks": "📦 Stocks",
           "achats": "🛒 Achats", "ressources": "👷 Ressources", "budgets": "💰 Budgets", "analyses": "📊 Analyses",
           "terrain": "📱 Mode terrain", "parametres": "⚙️ Paramètres & imports"}
if "gm_mod" not in st.session_state:
    st.session_state["gm_mod"] = "accueil"


def aller(module):
    st.session_state["gm_mod"] = module


with st.sidebar:
    st.markdown("### 🔧 GMAO")
    st.radio("Module", list(MODULES), format_func=MODULES.get, key="gm_mod", label_visibility="collapsed")

# ----------------------------------------------------------------------------- contexte partagé
ref = mt.referentiel_sites(data.sites)
libelles = dict(zip(ref["site_id"], ref["libelle"]))
info = ref.set_index("site_id")
gc.migrer_interventions()
tables_j = gmao_ui.charger_tables()
gc.initialiser_articles_depuis_journaux(gj.normaliser_defauts(tables_j.get("defauts")))
bi = gc.table("gmao_bi")
di = gc.table("gmao_di")
auj = pd.Timestamp(gc.maintenant()).normalize()

eq_rows, _ = get_effective_roster(data.equipes_rows, data.unassigned)
EQUIPES = {}
if eq_rows is not None and not eq_rows.empty:
    for (ant, zone), g in eq_rows.groupby(["Antenne", "Zone"]):
        ing = [str(x) for x, r in zip(g["Nom"], g["Rôle"]) if r == "Ingénieur" and "MANQUANT" not in str(x)]
        autres = [str(x) for x in g["Nom"] if "MANQUANT" not in str(x) and str(x) not in ing]
        EQUIPES[f"{ant} — Zone {zone}"] = ing + autres
for p in gc.table("gmao_prestataires")["nom"].dropna():
    EQUIPES[f"Prestataire — {p}"] = []
EQUIPES.setdefault("Prestataire / autre", [])


def classe_site() -> pd.Series:
    """Classe d'exploitation (journal) + arrêt imposé par un BI correctif ouvert."""
    cl = gmao_ui.classes_sites(ref)
    cl = cl if cl is not None else pd.Series("Non renseigné", index=ref["site_id"])
    arr = set(bi.loc[bi["statut"].isin(gc.STATUTS_BI_OUVERTS) & bi["centrale_arret"], "site_id"])
    return cl.where(~cl.index.isin(arr), "À l'arrêt")


ICONES = {"Fonctionnelle (H24)": "🟢", "Fonctionnement partiel": "🟠", "À l'arrêt": "🔴", "Non renseigné": "⚪"}


def infos_site(sid):
    r = info.loc[sid]
    return {"site_id": sid, "site": r["Nom du site"], "phase": r["Phase"], "region": r["Région"]}


def choisir_equipe(prefixe, defaut=None):
    c1, c2 = st.columns(2)
    noms = list(EQUIPES)
    eq = c1.selectbox("Équipe", ["— non affecté —"] + noms, key=f"{prefixe}_eq",
                      index=(noms.index(defaut) + 1) if defaut in noms else 0)
    chef = None
    if eq != "— non affecté —":
        options = EQUIPES.get(eq, []) + ["Autre (saisir)"]
        chef = c2.selectbox("Chef d'équipe", options, key=f"{prefixe}_chef")
        if chef == "Autre (saisir)":
            chef = c2.text_input("Nom du chef d'équipe", key=f"{prefixe}_chef_txt")
    return (None if eq == "— non affecté —" else eq), chef


def _fig(fig, **kw):
    fig = plotly_base_layout(fig, **kw)
    fig.update_layout(separators=", ")
    return fig


def compteurs(titre, valeurs: dict, couleurs: dict):
    st.markdown(f"**{titre}**")
    cols = st.columns(len(valeurs))
    for c, (k, v) in zip(cols, valeurs.items()):
        c.markdown(f"<div class='gm-compteur' style='background:{couleurs.get(k, NAVY)}'>{k}<b>{v}</b></div>",
                   unsafe_allow_html=True)


def ok(msg):
    st.session_state["_gm_ok"] = msg
    st.rerun()


if st.session_state.get("_gm_ok"):
    st.success("💾 " + st.session_state.pop("_gm_ok"))

mod = st.session_state["gm_mod"]
st.title("🔧 GMAO — Maintenance des centrales")


# ============================================================================= ACCUEIL
def accueil():
    st.caption("Gestion de la maintenance assistée par ordinateur du parc solaire : demandes et bons d'intervention, "
               "arborescence des équipements, préventif, stocks, achats, budgets, ressources et analyses. Toutes les "
               "saisies sont enregistrées dans la base de données.")
    section_title("MES MENUS")
    for ligne in (TUILES[:5], TUILES[5:]):
        cols = st.columns(5)
        for col, (k, lib, ico, _) in zip(cols, ligne):
            col.button(f"{ico}\n{lib}", key=f"tuile_{k}", on_click=aller, args=(k,), width="stretch")

    c1, c2 = st.columns(2)
    with c1:
        compteurs("Mes infos DI", {s: int((di["statut"] == s).sum()) for s in gc.STATUTS_DI},
                  {"Nouvelle": "#C0392B", "Acceptée": "#27AE60", "Refusée": "#7F8C8D", "Annulée": "#566573"})
    with c2:
        vals = {"À planif.": int((bi["statut"] == "À planifier").sum()), "Planifié": int((bi["statut"] == "Planifié").sum()),
                "En cours": int((bi["statut"] == "En cours").sum()),
                "Att. pièces": int((bi["statut"] == "En attente de pièces").sum()),
                "Terminé": int((bi["statut"] == "Terminé").sum()), "Clôturé": int((bi["statut"] == "Clôturé").sum())}
        compteurs("Mes infos BI", vals, {"À planif.": "#C0392B", "Planifié": "#2E86C1", "En cours": "#E67E22",
                                         "Att. pièces": "#8E44AD", "Terminé": "#27AE60", "Clôturé": "#1F3A5F"})
    st.write("")
    cl = classe_site()
    k = gc.kpis_bi(bi, auj)
    niv = gc.niveaux_stock()
    kpi_row([("Centrales en service", f"{int(cl.isin(['Fonctionnelle (H24)', 'Fonctionnement partiel']).sum())} / {len(cl)}", None),
             ("Centrales à l'arrêt", str(int((cl == "À l'arrêt").sum())), None),
             ("BI en retard", str(k["en_retard"]), None),
             ("BI non affectés", str(k["non_affectes"]), None),
             ("Articles sous le stock mini", str(int(niv["alerte"].sum())) if len(niv) else "0", None)])

    c1, c2 = st.columns([3, 2])
    with c1:
        section_title("INTERVENTIONS NON AFFECTÉES")
        na = bi[bi["statut"].isin(gc.STATUTS_BI_OUVERTS) & (bi["equipe"].isna() | (bi["equipe"].astype(str) == ""))]
        if na.empty:
            st.success("Tous les bons d'intervention ouverts sont affectés à une équipe.")
        else:
            st.dataframe(na[["id", "site", "type", "priorite", "description", "date_creation"]].rename(columns={
                "id": "BI", "site": "Centrale", "type": "Type", "priorite": "Priorité", "description": "Description",
                "date_creation": "Créé le"}), hide_index=True, width="stretch", height=260,
                column_config={"Créé le": st.column_config.DateColumn(format="DD/MM/YYYY")})
            st.button("➡️ Affecter dans « Bons d'intervention »", on_click=aller, args=("bi",), key="acc_aff")
    with c2:
        section_title("DEMANDE D'INTERVENTION RAPIDE")
        formulaire_di("acc")


# ============================================================================= DI
def formulaire_di(prefixe):
    n = st.session_state.get(f"_{prefixe}_n", 0)
    sid = st.selectbox("Centrale", list(ref["site_id"]), format_func=libelles.get, key=f"{prefixe}_site_{n}",
                       index=None, placeholder="Rechercher une centrale…")
    c1, c2 = st.columns(2)
    sysm = c1.selectbox("Système", gc.SYSTEMES, key=f"{prefixe}_sys_{n}")
    prio = c2.selectbox("Priorité", gc.PRIORITES, index=2, key=f"{prefixe}_prio_{n}")
    desc = st.text_area("Description du problème", key=f"{prefixe}_desc_{n}", height=80)
    c1, c2 = st.columns(2)
    dem = c1.text_input("Demandeur", key=f"{prefixe}_dem_{n}")
    arret = c2.checkbox("Centrale à l'arrêt", key=f"{prefixe}_arr_{n}")
    if st.button("🚨 Enregistrer la demande", type="primary", key=f"{prefixe}_ok_{n}", disabled=not (sid and desc)):
        ids = gc.ajouter("gmao_di", [{**infos_site(sid), "date": pd.Timestamp(gc.maintenant()), "demandeur": dem,
                                      "systeme": sysm, "description": desc, "priorite": prio, "centrale_arret": arret,
                                      "statut": "Nouvelle"}], "DI", f"nouvelle demande d'intervention — {libelles[sid]}")
        st.session_state[f"_{prefixe}_n"] = n + 1
        ok(f"Demande {ids[0]} enregistrée.")


def module_di():
    t1, t2 = st.tabs(["📝 Nouvelle demande", "📋 Demandes à traiter et historique"])
    with t1:
        formulaire_di("di")
    with t2:
        f = st.multiselect("Statut", gc.STATUTS_DI, default=["Nouvelle"], key="di_f")
        v = di[di["statut"].isin(f)] if f else di
        st.dataframe(v.sort_values("date", ascending=False).drop(columns=["site_id"]), hide_index=True, width="stretch",
                     height=320, column_config={"date": st.column_config.DatetimeColumn("Date", format="DD/MM/YYYY HH:mm")})
        nouvelles = di[di["statut"] == "Nouvelle"]
        if not nouvelles.empty:
            st.markdown("**Traiter une demande**")
            did = st.selectbox("Demande", nouvelles["id"], key="di_sel",
                               format_func=lambda i: f"{i} — " + str(nouvelles.set_index('id').at[i, 'site']) + " — "
                               + str(nouvelles.set_index('id').at[i, 'description'])[:60])
            d = nouvelles.set_index("id").loc[did]
            c1, c2 = st.columns(2)
            typ = c1.selectbox("Type de BI", gc.TYPES_BI, key="di_typ")
            date_prev = c2.date_input("Date prévue", value=auj.date(), key="di_dp", format="DD/MM/YYYY")
            eq, chef = choisir_equipe("di_t")
            motif = st.text_input("Motif (en cas de refus)", key="di_motif")
            b1, b2 = st.columns(2)
            if b1.button("✅ Accepter et créer le BI", type="primary", key="di_acc"):
                ids = gc.ajouter("gmao_bi", [{"di_id": did, "origine": "DI", "type": typ, "priorite": d["priorite"],
                                              "site_id": d["site_id"], "site": d["site"], "phase": d["phase"],
                                              "region": d["region"], "systeme": d["systeme"], "description": d["description"],
                                              "statut": "Planifié" if eq else "À planifier", "centrale_arret": bool(d["centrale_arret"]),
                                              "date_creation": pd.Timestamp(gc.maintenant()), "date_prevue": pd.Timestamp(date_prev),
                                              "date_arret": d["date"] if d["centrale_arret"] else None,
                                              "equipe": eq, "chef": chef}], "BI", f"BI créé depuis {did}")
                gc.modifier("gmao_di", did, {"statut": "Acceptée", "bi_id": ids[0]}, f"{did} acceptée → {ids[0]}")
                ok(f"{did} acceptée : bon d'intervention {ids[0]} créé.")
            if b2.button("⛔ Refuser", key="di_ref", disabled=not motif):
                gc.modifier("gmao_di", did, {"statut": "Refusée", "motif": motif}, f"{did} refusée")
                ok(f"{did} refusée.")


# ============================================================================= BI
def module_bi():
    t1, t2, t3 = st.tabs(["📋 Liste des BI", "🛠️ Traiter un BI", "➕ Créer un BI"])
    with t1:
        c = st.columns(5)
        fs = c[0].multiselect("Statut", gc.STATUTS_BI, default=gc.STATUTS_BI_OUVERTS, key="bi_fs")
        ft = c[1].multiselect("Type", gc.TYPES_BI, key="bi_ft")
        fp = c[2].multiselect("Priorité", gc.PRIORITES, key="bi_fp")
        fe = c[3].multiselect("Équipe", sorted(bi["equipe"].dropna().unique()), key="bi_fe")
        fq = c[4].text_input("Recherche", key="bi_fq")
        v = bi.copy()
        for col, val in (("statut", fs), ("type", ft), ("priorite", fp), ("equipe", fe)):
            if val:
                v = v[v[col].isin(val)]
        if fq:
            v = v[v.astype(str).apply(lambda s: s.str.contains(fq, case=False, regex=False)).any(axis=1)]
        v = gc.couts_bi(v)
        st.caption(f"{len(v)} bon(s) d'intervention")
        st.dataframe(v.sort_values("id", ascending=False)[[
            "id", "site", "type", "priorite", "statut", "systeme", "description", "date_prevue", "equipe", "chef",
            "centrale_arret", "temps_arret_h", "cout_total", "origine"]], hide_index=True, width="stretch", height=420,
            column_config={"date_prevue": st.column_config.DateColumn("Prévu le", format="DD/MM/YYYY"),
                           "centrale_arret": st.column_config.CheckboxColumn("Arrêt"),
                           "cout_total": st.column_config.NumberColumn("Coût (FCFA)", format="localized")})
        buf = io.BytesIO()
        v.to_excel(buf, index=False)
        st.download_button("⬇️ Exporter (Excel)", buf.getvalue(), "bons_intervention.xlsx", key="bi_dl")
        aff = v[v["statut"].isin(gc.STATUTS_BI_OUVERTS)]
        if not aff.empty:
            with st.expander(f"👷 Affecter en masse les {len(aff)} BI ouverts affichés"):
                st.caption("Filtre d'abord la liste (par exemple par recherche sur une région ou une antenne), puis affecte.")
                eq, chef = choisir_equipe("bim")
                if st.button("Affecter", key="bim_ok", disabled=not eq):
                    tout = gc.table("gmao_bi")
                    m = tout["id"].isin(aff["id"])
                    tout.loc[m, "equipe"] = eq
                    tout.loc[m, "chef"] = chef
                    tout.loc[m & (tout["statut"] == "À planifier"), "statut"] = "Planifié"
                    gc.sauver("gmao_bi", tout, f"{int(m.sum())} BI affectés à {eq}")
                    ok(f"{int(m.sum())} BI affectés à {eq}.")
    with t2:
        ouverts = bi[bi["statut"].isin(gc.STATUTS_BI_OUVERTS + ["Terminé"])]
        if ouverts.empty:
            st.info("Aucun bon d'intervention à traiter.")
        else:
            bid = st.selectbox("Bon d'intervention", ouverts["id"][::-1], key="bi_sel",
                               format_func=lambda i: f"{i} — {ouverts.set_index('id').at[i, 'site']} — "
                               f"{ouverts.set_index('id').at[i, 'statut']} — {str(ouverts.set_index('id').at[i, 'description'])[:50]}")
            traiter_bi(bid)
    with t3:
        n = st.session_state.get("_bic_n", 0)
        sites = st.multiselect("Centrale(s)", list(ref["site_id"]), format_func=libelles.get, key=f"bic_s_{n}")
        c1, c2, c3 = st.columns(3)
        typ = c1.selectbox("Type", gc.TYPES_BI, key=f"bic_t_{n}")
        prio = c2.selectbox("Priorité", gc.PRIORITES, index=2, key=f"bic_p_{n}")
        sysm = c3.selectbox("Système", gc.SYSTEMES, key=f"bic_sy_{n}")
        desc = st.text_area("Description / travaux à réaliser", key=f"bic_d_{n}", height=80)
        c1, c2, c3 = st.columns(3)
        dp = c1.date_input("Date prévue", value=auj.date(), key=f"bic_dp_{n}", format="DD/MM/YYYY")
        duree = c2.number_input("Durée estimée (h)", 0.0, 500.0, 4.0, 0.5, key=f"bic_du_{n}")
        arret = c3.checkbox("Centrale à l'arrêt", key=f"bic_ar_{n}")
        eq, chef = choisir_equipe(f"bic_{n}")
        if st.button("➕ Créer", type="primary", disabled=not (sites and desc), key=f"bic_ok_{n}"):
            ids = gc.ajouter("gmao_bi", [{**infos_site(s), "origine": "Direct", "type": typ, "priorite": prio, "systeme": sysm,
                                          "description": desc, "statut": "Planifié" if eq else "À planifier",
                                          "centrale_arret": arret, "date_creation": pd.Timestamp(gc.maintenant()),
                                          "date_arret": pd.Timestamp(gc.maintenant()) if arret else None,
                                          "date_prevue": pd.Timestamp(dp), "duree_interv_h": duree, "equipe": eq, "chef": chef}
                                         for s in sites], "BI", f"{len(sites)} BI créé(s)")
            st.session_state["_bic_n"] = n + 1
            ok(f"{len(ids)} bon(s) créé(s) : " + ", ".join(ids[:5]) + ("…" if len(ids) > 5 else ""))


def traiter_bi(bid):
    b = bi.set_index("id").loc[bid]
    st.markdown(f"**{bid}** · {b['site']} ({b['phase']}) · {b['type']} · priorité {b['priorite']} · statut **{b['statut']}**")
    st.caption(str(b["description"] or ""))
    a1, a2, a3 = st.tabs(["🗓️ Planifier / affecter", "🔩 Pièces consommées", "✅ Clôturer"])
    with a1:
        c1, c2 = st.columns(2)
        dp = c1.date_input("Date prévue", value=(b["date_prevue"] if pd.notna(b["date_prevue"]) else auj).date(),
                           key=f"tb_dp_{bid}", format="DD/MM/YYYY")
        statut = c2.selectbox("Statut", gc.STATUTS_BI, index=gc.STATUTS_BI.index(b["statut"]) if b["statut"] in gc.STATUTS_BI else 0,
                              key=f"tb_st_{bid}")
        eq, chef = choisir_equipe(f"tb_{bid}", b["equipe"])
        interv = st.text_input("Intervenants", value=str(b["intervenants"] or ""), key=f"tb_in_{bid}")
        if st.button("💾 Enregistrer", key=f"tb_ok_{bid}"):
            vals = {"date_prevue": pd.Timestamp(dp), "statut": statut, "equipe": eq or b["equipe"],
                    "chef": chef or b["chef"], "intervenants": interv}
            if statut == "En cours" and pd.isna(b["date_debut"]):
                vals["date_debut"] = pd.Timestamp(gc.maintenant())
            if statut == "Planifié" and not (eq or b["equipe"]):
                st.error("Affecte une équipe pour planifier ce BI.")
            else:
                gc.modifier("gmao_bi", bid, vals, f"{bid} mis à jour ({statut})")
                ok(f"{bid} mis à jour.")
    with a2:
        niv = gc.niveaux_stock()
        mv = gc.table("gmao_mouvements")
        deja = mv[(mv["bi_id"] == bid) & (mv["type"] == "Sortie")]
        if not deja.empty:
            st.dataframe(deja[["date", "code", "quantite", "magasin"]], hide_index=True, width="stretch")
        if niv.empty:
            st.info("Catalogue d'articles vide : ajoute des articles dans « Stocks ».")
        else:
            c1, c2, c3 = st.columns([3, 1, 2])
            code = c1.selectbox("Article", niv["code"], key=f"tb_art_{bid}",
                                format_func=lambda c: f"{c} — {niv.set_index('code').at[c, 'designation']} "
                                f"(stock {niv.set_index('code').at[c, 'stock']:.0f})")
            q = c2.number_input("Quantité", 1.0, 100000.0, 1.0, 1.0, key=f"tb_q_{bid}")
            mag = c3.selectbox("Magasin", gc.MAGASINS, key=f"tb_mag_{bid}")
            if st.button("➖ Sortir du stock pour ce BI", key=f"tb_out_{bid}"):
                gc.ajouter("gmao_mouvements", [{"date": pd.Timestamp(gc.maintenant()), "code": code, "type": "Sortie",
                                                "quantite": q, "magasin": mag, "bi_id": bid, "motif": f"Consommation {bid}"}],
                           "MV", f"sortie de stock {code} × {q:g} pour {bid}")
                ok(f"{q:g} × {code} imputé(s) à {bid}.")
    with a3:
        c1, c2, c3 = st.columns(3)
        dfin = c1.date_input("Date de fin d'intervention", value=auj.date(), key=f"tb_df_{bid}", format="DD/MM/YYYY")
        duree = c2.number_input("Durée de l'intervention (h)", 0.0, 1000.0,
                                float(b["duree_interv_h"]) if pd.notna(b["duree_interv_h"]) else 0.0, 0.5, key=f"tb_du_{bid}")
        arret = c3.checkbox("La centrale était à l'arrêt", value=bool(b["centrale_arret"]), key=f"tb_ar_{bid}")
        ta = None
        if arret:
            c1, c2, c3 = st.columns(3)
            da = c1.date_input("Début de l'arrêt", value=(b["date_arret"] if pd.notna(b["date_arret"]) else auj).date(),
                               key=f"tb_da_{bid}", format="DD/MM/YYYY")
            dr = c2.date_input("Remise en service", value=dfin, key=f"tb_dr_{bid}", format="DD/MM/YYYY")
            calc = max((pd.Timestamp(dr) - pd.Timestamp(da)).total_seconds() / 3600, 0)
            ta = c3.number_input("Temps d'arrêt (h)", 0.0, 100000.0, float(b["temps_arret_h"]) if pd.notna(b["temps_arret_h"]) else calc,
                                 1.0, key=f"tb_ta_{bid}_{da}_{dr}")
        travaux = st.text_area("Travaux réalisés", value=str(b["travaux"] or ""), key=f"tb_tr_{bid}", height=80)
        cause = st.selectbox("Cause de la défaillance", ["", "Usure / fin de vie", "Défaut de fabrication", "Surcharge",
                                                          "Mauvaise utilisation", "Vol / vandalisme", "Intempéries",
                                                          "Défaut d'entretien", "Cause inconnue"], key=f"tb_ca_{bid}")
        c1, c2, c3 = st.columns(3)
        cmo = c1.number_input("Coût main d'œuvre (FCFA)", 0.0, 1e10, float(b["cout_mo"] or 0), 5000.0, key=f"tb_mo_{bid}")
        cpr = c2.number_input("Coût prestataire (FCFA)", 0.0, 1e10, float(b["cout_presta"] or 0), 5000.0, key=f"tb_pr_{bid}")
        presta = c3.text_input("Prestataire", value=str(b["prestataire"] or ""), key=f"tb_pn_{bid}")
        if st.button("✅ Clôturer le BI", type="primary", key=f"tb_clo_{bid}"):
            vals = {"statut": "Clôturé", "date_fin": pd.Timestamp(dfin), "duree_interv_h": duree, "centrale_arret": arret,
                    "travaux": travaux, "cause": cause or None, "cout_mo": cmo, "cout_presta": cpr, "prestataire": presta or None}
            if arret:
                vals.update({"date_arret": pd.Timestamp(da), "date_remise": pd.Timestamp(dr), "temps_arret_h": round(ta, 1)})
            gc.modifier("gmao_bi", bid, vals, f"{bid} clôturé")
            if pd.notna(b["di_id"]):
                gc.modifier("gmao_di", b["di_id"], {"statut": "Acceptée"}, f"DI {b['di_id']} soldée")
            ok(f"{bid} clôturé.")


# ============================================================================= ÉQUIPEMENTS
def module_equipements():
    cl = classe_site()
    r = ref.assign(classe=ref["site_id"].map(cl))
    c1, c2, c3 = st.columns([1, 1, 2])
    reg = c1.selectbox("Région", ["Toutes"] + sorted(r["Région"].dropna().unique()), key="eq_reg")
    ph = c2.selectbox("Phase", ["Toutes"] + sorted(r["Phase"].dropna().unique()), key="eq_ph")
    etat = c3.multiselect("État", list(ICONES), key="eq_etat", format_func=lambda e: f"{ICONES[e]} {e}")
    v = r
    if reg != "Toutes":
        v = v[v["Région"] == reg]
    if ph != "Toutes":
        v = v[v["Phase"] == ph]
    if etat:
        v = v[v["classe"].isin(etat)]
    st.caption(" · ".join(f"{ICONES[e]} {e} : {int((v['classe'] == e).sum())}" for e in ICONES) + f" — {len(v)} centrale(s)")
    col_a, col_b = st.columns([2, 3])
    with col_a:
        st.markdown("**Arborescence**")
        for rg, grp in v.groupby("Région"):
            with st.expander(f"{rg} ({len(grp)})", expanded=(reg != "Toutes")):
                for p, gp in grp.groupby("Phase"):
                    st.markdown(f"**{p}** — " + ", ".join(f"{ICONES.get(c, '⚪')} {n}" for n, c in zip(gp["Nom du site"], gp["classe"])))
    with col_b:
        sid = st.selectbox("Fiche d'une centrale", list(v["site_id"]), format_func=libelles.get, key="eq_site",
                           index=None, placeholder="Choisir une centrale…")
        if sid:
            fiche_site(sid, cl.get(sid))


def fiche_site(sid, classe):
    s = info.loc[sid]
    stat = gj.statuts_courants(tables_j.get("statuts"))
    st_row = stat[stat["cle_site"] == gj.cle(s["Nom du site"])] if not stat.empty else pd.DataFrame()
    st.markdown(f"### {ICONES.get(classe, '⚪')} {s['Nom du site']}")
    st.caption(f"{s['Phase']} · {s['Région']} · {s.get('Département', '')} · {s['Puissance (kWc)']:.1f} kWc · antenne "
               f"{s['Antenne proposée']} · état : {classe}"
               + (f" · cause : {st_row['causes'].iloc[0]}" if len(st_row) and pd.notna(st_row['causes'].iloc[0]) else ""))
    bis = bi[bi["site_id"] == sid]
    dj = gj.normaliser_defauts(tables_j.get("defauts"))
    dj = dj[dj["cle_site"] == gj.cle(s["Nom du site"])] if not dj.empty else dj
    kpi_row([("BI ouverts", str(int(bis["statut"].isin(gc.STATUTS_BI_OUVERTS).sum())), None),
             ("BI clôturés", str(int((bis["statut"] == "Clôturé").sum())), None),
             ("Défauts (journaux)", str(len(dj)), None),
             ("Temps d'arrêt cumulé (BI)", f"{bis['temps_arret_h'].sum():,.0f} h".replace(",", " "), None)])
    t1, t2, t3 = st.tabs(["⚙️ Systèmes et équipements", "🧾 Interventions", "📜 Historique des journaux"])
    with t1:
        eqs = gc.table("gmao_equipements")
        eqs = eqs[eqs["site_id"] == sid]
        sysm = pd.DataFrame({"Système": gc.SYSTEMES})
        sysm["Équipements enregistrés"] = sysm["Système"].map(eqs.groupby("systeme")["quantite"].sum()).fillna(0).astype(int)
        sysm["BI ouverts"] = sysm["Système"].map(bis[bis["statut"].isin(gc.STATUTS_BI_OUVERTS)].groupby("systeme").size()).fillna(0).astype(int)
        if not dj.empty:
            dj2 = dj.assign(sys=dj["categorie"].map(gc.CATEGORIE_VERS_SYSTEME))
            sysm["Défauts historiques"] = sysm["Système"].map(dj2.groupby("sys").size()).fillna(0).astype(int)
        st.dataframe(sysm, hide_index=True, width="stretch")
        if not eqs.empty:
            st.dataframe(eqs.drop(columns=["site_id", "site"]), hide_index=True, width="stretch")
        with st.expander("➕ Ajouter un équipement"):
            n = st.session_state.get("_eqa_n", 0)
            c1, c2, c3 = st.columns(3)
            sy = c1.selectbox("Système", gc.SYSTEMES, key=f"eqa_s_{n}")
            des = c2.text_input("Désignation", key=f"eqa_d_{n}", placeholder="ex. Onduleur 30 kVA")
            mm = c3.text_input("Marque / modèle", key=f"eqa_m_{n}")
            c1, c2, c3, c4 = st.columns(4)
            ns = c1.text_input("N° de série", key=f"eqa_n_{n}")
            q = c2.number_input("Quantité", 1, 100000, 1, key=f"eqa_q_{n}")
            dmes = c3.date_input("Mise en service", value=None, key=f"eqa_dm_{n}", format="DD/MM/YYYY")
            crit = c4.selectbox("Criticité", ["Haute", "Moyenne", "Basse"], key=f"eqa_c_{n}")
            if st.button("Ajouter", key=f"eqa_ok_{n}", disabled=not des):
                gc.ajouter("gmao_equipements", [{"site_id": sid, "site": s["Nom du site"], "systeme": sy, "designation": des,
                                                 "marque_modele": mm, "numero_serie": ns, "quantite": q,
                                                 "date_mes": pd.Timestamp(dmes) if dmes else None, "criticite": crit,
                                                 "statut": "En service"}], "EQ", f"équipement ajouté — {s['Nom du site']}")
                st.session_state["_eqa_n"] = n + 1
                ok("Équipement ajouté.")
    with t2:
        st.dataframe(gc.couts_bi(bis).sort_values("id", ascending=False)[[
            "id", "type", "statut", "systeme", "description", "date_prevue", "date_fin", "temps_arret_h", "equipe", "chef",
            "cout_total"]], hide_index=True, width="stretch")
    with t3:
        if dj.empty:
            st.info("Aucun défaut de cette centrale dans les journaux importés.")
        else:
            st.dataframe(dj.sort_values("date_incident", ascending=False)[[
                "source", "date_incident", "categorie", "materiel", "description", "mesure", "priorite", "resultat",
                "delai_resolution_j"]], hide_index=True, width="stretch",
                column_config={"date_incident": st.column_config.DateColumn("Incident", format="DD/MM/YYYY")})


# ============================================================================= PLANNING
def module_planning():
    t1, t2, t3 = st.tabs(["🗓️ Planning", "📚 Gammes préventives", "⚙️ Générer le préventif"])
    with t1:
        c1, c2, c3 = st.columns(3)
        d0 = c1.date_input("Du", value=(auj - pd.Timedelta(days=7)).date(), key="pl_d0", format="DD/MM/YYYY")
        d1 = c2.date_input("Au", value=(auj + pd.Timedelta(days=60)).date(), key="pl_d1", format="DD/MM/YYYY")
        grp = c3.radio("Regrouper par", ["Équipe", "Centrale", "Type"], horizontal=True, key="pl_g")
        p = bi[bi["date_prevue"].between(pd.Timestamp(d0), pd.Timestamp(d1)) & bi["statut"].isin(gc.STATUTS_BI_OUVERTS + ["Terminé", "Clôturé"])].copy()
        if p.empty:
            st.info("Aucun BI planifié sur la période.")
        else:
            p["debut"] = p["date_prevue"]
            p["fin"] = p["date_prevue"] + pd.to_timedelta(p["duree_interv_h"].fillna(4).clip(lower=1), unit="h") + pd.Timedelta(hours=12)
            p["axe"] = {"Équipe": p["equipe"].fillna("Non affecté"), "Centrale": p["site"], "Type": p["type"]}[grp]
            fig = px.timeline(p, x_start="debut", x_end="fin", y="axe", color="statut", hover_data=["id", "site", "description"],
                              color_discrete_map={"À planifier": RED, "Planifié": BLUE, "En cours": GOLD,
                                                  "En attente de pièces": "#8E44AD", "Terminé": "#27AE60", "Clôturé": NAVY})
            fig.add_vline(x=auj, line_dash="dot", line_color=RED)
            fig.update_yaxes(autorange="reversed", title="")
            st.plotly_chart(_fig(fig, height=max(320, 26 * p["axe"].nunique() + 120)), width="stretch")
            p["semaine"] = p["date_prevue"].dt.to_period("W").dt.start_time
            charge = p.pivot_table(index=p["equipe"].fillna("Non affecté"), columns="semaine", values="duree_interv_h",
                                   aggfunc="sum").fillna(0)
            charge.columns = [c.strftime("S%V (%d/%m)") for c in charge.columns]
            st.markdown("**Charge planifiée par équipe et par semaine (heures)**")
            st.dataframe(charge.round(1), width="stretch")
        retard = bi[bi["statut"].isin(gc.STATUTS_BI_OUVERTS) & (bi["date_prevue"] < auj)]
        st.markdown(f"**BI en retard sur la date prévue : {len(retard)}**")
        if not retard.empty:
            st.dataframe(retard[["id", "site", "type", "priorite", "statut", "date_prevue", "equipe"]], hide_index=True,
                         width="stretch", column_config={"date_prevue": st.column_config.DateColumn(format="DD/MM/YYYY")})
    with t2:
        plans = gc.table("gmao_plans")
        if not plans.empty:
            st.dataframe(plans, hide_index=True, width="stretch",
                         column_config={"prochaine_echeance": st.column_config.DateColumn(format="DD/MM/YYYY")})
        st.markdown("**Nouvelle gamme préventive**")
        n = st.session_state.get("_pla_n", 0)
        c1, c2, c3 = st.columns(3)
        lib = c1.text_input("Libellé", key=f"pla_l_{n}", placeholder="ex. Nettoyage des panneaux PV")
        sy = c2.selectbox("Système", gc.SYSTEMES, key=f"pla_s_{n}")
        typ = c3.selectbox("Type", gc.TYPES_BI[1:], key=f"pla_t_{n}")
        c1, c2, c3, c4 = st.columns(4)
        per = c1.number_input("Périodicité (jours)", 1, 3650, 90, key=f"pla_p_{n}")
        du = c2.number_input("Durée par site (h)", 0.5, 200.0, 2.0, 0.5, key=f"pla_d_{n}")
        ech = c3.date_input("Première échéance", value=auj.date(), key=f"pla_e_{n}", format="DD/MM/YYYY")
        eq = c4.selectbox("Équipe", ["— selon la zone —"] + list(EQUIPES), key=f"pla_eq_{n}")
        c1, c2 = st.columns(2)
        phs = c1.multiselect("Phases concernées (vide = toutes)", sorted(ref["Phase"].unique()), key=f"pla_ph_{n}")
        rgs = c2.multiselect("Régions concernées (vide = toutes)", sorted(ref["Région"].dropna().unique()), key=f"pla_rg_{n}")
        cons = st.text_area("Consignes / points de contrôle", key=f"pla_c_{n}", height=70)
        if st.button("➕ Créer la gamme", key=f"pla_ok_{n}", disabled=not lib):
            gc.ajouter("gmao_plans", [{"libelle": lib, "type": typ, "systeme": sy, "phases": "; ".join(phs), "regions": "; ".join(rgs),
                                       "periodicite_j": per, "duree_h": du, "equipe": None if eq.startswith("—") else eq,
                                       "prochaine_echeance": pd.Timestamp(ech), "actif": True, "consignes": cons}],
                       "GP", f"gamme préventive créée — {lib}")
            st.session_state["_pla_n"] = n + 1
            ok(f"Gamme « {lib} » créée.")
    with t3:
        plans = gc.table("gmao_plans")
        hz = st.slider("Horizon (jours)", 7, 180, 30, key="pl_hz")
        dues = plans[plans["actif"] & (plans["prochaine_echeance"] <= auj + pd.Timedelta(days=hz))]
        st.caption(f"{len(dues)} gamme(s) arrivent à échéance dans les {hz} prochains jours.")
        if st.button("⚙️ Générer les BI préventifs", type="primary", key="pl_gen", disabled=dues.empty):
            nb = gc.generer_preventif(ref, hz)
            ok(f"{nb} BI préventif(s) planifié(s).")


# ============================================================================= STOCKS
def module_stocks():
    niv = gc.niveaux_stock()
    if not niv.empty:
        kpi_row([("Articles", str(len(niv)), None), ("Sous le stock mini", str(int(niv["alerte"].sum())), None),
                 ("Valeur du stock (FCFA)", f"{niv['valeur'].sum():,.0f}".replace(",", " "), None)])
    t1, t2, t3, t4 = st.tabs(["📦 Niveaux de stock", "🔁 Mouvement", "📚 Catalogue", "📈 Consommations"])
    with t1:
        if niv.empty:
            st.info("Catalogue vide.")
        else:
            f = st.checkbox("Uniquement les articles en alerte", key="stk_al")
            v = niv[niv["alerte"]] if f else niv
            st.dataframe(v, hide_index=True, width="stretch", height=420,
                         column_config={"alerte": st.column_config.CheckboxColumn("⚠️ Alerte"),
                                        "valeur": st.column_config.NumberColumn("Valeur (FCFA)", format="localized")})
    with t2:
        if niv.empty:
            st.info("Ajoute d'abord des articles au catalogue.")
        else:
            n = st.session_state.get("_mv_n", 0)
            c1, c2, c3 = st.columns([3, 1, 1])
            code = c1.selectbox("Article", niv["code"], key=f"mv_c_{n}",
                                format_func=lambda c: f"{c} — {niv.set_index('code').at[c, 'designation']}")
            typ = c2.selectbox("Mouvement", ["Entrée", "Sortie", "Ajustement"], key=f"mv_t_{n}")
            q = c3.number_input("Quantité", value=1.0, step=1.0, key=f"mv_q_{n}",
                                help="Ajustement : quantité positive ou négative (inventaire).")
            c1, c2 = st.columns(2)
            mag = c1.selectbox("Magasin", gc.MAGASINS, key=f"mv_m_{n}")
            motif = c2.text_input("Motif / référence", key=f"mv_mo_{n}")
            if st.button("Enregistrer le mouvement", type="primary", key=f"mv_ok_{n}"):
                gc.ajouter("gmao_mouvements", [{"date": pd.Timestamp(gc.maintenant()), "code": code, "type": typ,
                                                "quantite": q, "magasin": mag, "motif": motif}], "MV",
                           f"{typ.lower()} de stock {code} × {q:g}")
                st.session_state["_mv_n"] = n + 1
                ok("Mouvement enregistré.")
        mv = gc.table("gmao_mouvements")
        if not mv.empty:
            st.dataframe(mv.sort_values("date", ascending=False).head(200), hide_index=True, width="stretch")
    with t3:
        art = gc.table("gmao_articles")
        st.caption("Modifie directement le tableau (stock mini, prix, magasin…) puis enregistre. Le catalogue de départ "
                   "reprend les codes matériel des journaux de maintenance.")
        ed = st.data_editor(art, num_rows="dynamic", hide_index=True, width="stretch", key="cat_ed",
                            column_config={"systeme": st.column_config.SelectboxColumn(options=gc.SYSTEMES),
                                           "magasin": st.column_config.SelectboxColumn(options=gc.MAGASINS)})
        if st.button("💾 Enregistrer le catalogue", key="cat_ok"):
            gc.sauver("gmao_articles", ed.dropna(subset=["code"]), "catalogue d'articles modifié")
            ok("Catalogue enregistré.")
    with t4:
        mv = gc.table("gmao_mouvements")
        so = mv[mv["type"] == "Sortie"]
        dj = gj.normaliser_defauts(tables_j.get("defauts"))
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Sorties de stock enregistrées (BI)**")
            if so.empty:
                st.caption("Aucune sortie enregistrée.")
            else:
                st.dataframe(so.groupby("code")["quantite"].sum().sort_values(ascending=False).rename("Quantité sortie"),
                             width="stretch")
        with c2:
            st.markdown("**Remplacements relevés dans les journaux**")
            if not dj.empty:
                r = dj[~dj["lineaire"]].groupby("materiel")["qte_remplacee"].sum().sort_values(ascending=False)
                st.dataframe(r[r > 0].rename("Quantité remplacée").head(25), width="stretch")


# ============================================================================= ACHATS
def module_achats():
    ach = gc.table("gmao_achats")
    art = gc.table("gmao_articles")
    kpi_row([(s, str(int((ach["statut"] == s).sum())), None) for s in gc.STATUTS_ACHAT[:4]]
            + [("Montant engagé (FCFA)", f"{ach.loc[ach['statut'].isin(['Commandée', 'Reçue']), 'montant'].sum():,.0f}".replace(",", " "), None)])
    t1, t2 = st.tabs(["🛒 Nouvelle demande d'achat", "📋 Suivi des achats"])
    with t1:
        n = st.session_state.get("_da_n", 0)
        niv = gc.niveaux_stock()
        alertes = niv[niv["alerte"]]["code"].tolist() if len(niv) else []
        if alertes:
            st.caption(f"⚠️ {len(alertes)} article(s) sous le stock mini : " + ", ".join(alertes[:10]))
        c1, c2, c3 = st.columns([3, 1, 1])
        code = c1.selectbox("Article", art["code"], key=f"da_c_{n}", index=None, placeholder="Choisir un article…",
                            format_func=lambda c: f"{c} — {art.set_index('code').at[c, 'designation']}")
        q = c2.number_input("Quantité", 1.0, 1e7, 1.0, key=f"da_q_{n}")
        pu = c3.number_input("Prix unitaire (FCFA)", 0.0, 1e10,
                             float(art.set_index("code").at[code, "prix_unitaire"] or 0) if code else 0.0, key=f"da_p_{n}_{code}")
        c1, c2 = st.columns(2)
        four = c1.text_input("Fournisseur", key=f"da_f_{n}")
        bid = c2.selectbox("BI concerné (facultatif)", [""] + bi["id"].tolist()[::-1], key=f"da_b_{n}")
        com = st.text_input("Commentaire", key=f"da_co_{n}")
        if st.button("Enregistrer la demande d'achat", type="primary", disabled=not code, key=f"da_ok_{n}"):
            gc.ajouter("gmao_achats", [{"date": pd.Timestamp(gc.maintenant()), "code": code,
                                        "designation": art.set_index("code").at[code, "designation"], "quantite": q,
                                        "fournisseur": four, "prix_unitaire": pu, "montant": q * pu, "statut": "Demande",
                                        "bi_id": bid or None, "commentaire": com}], "DA", f"demande d'achat {code} × {q:g}")
            st.session_state["_da_n"] = n + 1
            ok("Demande d'achat enregistrée.")
    with t2:
        st.dataframe(ach.sort_values("date", ascending=False), hide_index=True, width="stretch", height=320,
                     column_config={"montant": st.column_config.NumberColumn(format="localized")})
        enc = ach[~ach["statut"].isin(["Reçue", "Annulée"])]
        if not enc.empty:
            c1, c2, c3 = st.columns([3, 2, 1])
            aid = c1.selectbox("Achat", enc["id"], key="ach_sel",
                               format_func=lambda i: f"{i} — {enc.set_index('id').at[i, 'designation']} "
                               f"× {enc.set_index('id').at[i, 'quantite']:g} ({enc.set_index('id').at[i, 'statut']})")
            nst = c2.selectbox("Nouveau statut", gc.STATUTS_ACHAT, key="ach_st")
            mag = c3.selectbox("Magasin de réception", gc.MAGASINS, key="ach_mag")
            if st.button("Mettre à jour", key="ach_ok"):
                a = enc.set_index("id").loc[aid]
                vals = {"statut": nst}
                if nst == "Reçue":
                    vals["date_reception"] = pd.Timestamp(gc.maintenant())
                    gc.ajouter("gmao_mouvements", [{"date": pd.Timestamp(gc.maintenant()), "code": a["code"], "type": "Entrée",
                                                    "quantite": a["quantite"], "magasin": mag, "achat_id": aid,
                                                    "motif": f"Réception {aid}"}], "MV", f"entrée en stock — réception {aid}")
                gc.modifier("gmao_achats", aid, vals, f"{aid} → {nst}")
                ok(f"{aid} : {nst}" + (" (entrée en stock enregistrée)" if nst == "Reçue" else ""))


# ============================================================================= RESSOURCES
def module_ressources():
    t1, t2 = st.tabs(["👷 Équipes et charge", "🤝 Prestataires"])
    with t1:
        ouverts = bi[bi["statut"].isin(gc.STATUTS_BI_OUVERTS)]
        clos30 = bi[(bi["statut"] == "Clôturé") & (bi["date_fin"] >= auj - pd.Timedelta(days=30))]
        lignes = []
        for eq, membres in EQUIPES.items():
            o = ouverts[ouverts["equipe"] == eq]
            lignes.append({"Équipe": eq, "Membres": len(membres), "Chef / ingénieur": membres[0] if membres else "—",
                           "BI ouverts": len(o), "Heures planifiées": round(o["duree_interv_h"].fillna(0).sum(), 1),
                           "BI en retard": int((o["date_prevue"] < auj).sum()),
                           "BI clôturés (30 j)": int((clos30["equipe"] == eq).sum()),
                           "Centrales visitées (total)": bi.loc[bi["equipe"] == eq, "site_id"].nunique()})
        tab = pd.DataFrame(lignes)
        st.dataframe(tab, hide_index=True, width="stretch", height=420)
        if tab["BI ouverts"].sum():
            fig = px.bar(tab[tab["BI ouverts"] > 0], x="Équipe", y="Heures planifiées", color="BI en retard",
                         color_continuous_scale="Reds", title="Charge des équipes")
            st.plotly_chart(_fig(fig, height=340), width="stretch")
        aff = tables_j.get("affectations")
        if aff is not None and not aff.empty:
            st.markdown("**Affectation des centrales par zone (journal de maintenance)**")
            st.dataframe(aff.drop_duplicates("site").groupby(["zone", "responsable"]).size().rename("Centrales").reset_index(),
                         hide_index=True, width="stretch")
    with t2:
        pr = gc.table("gmao_prestataires")
        ed = st.data_editor(pr, num_rows="dynamic", hide_index=True, width="stretch", key="pr_ed",
                            column_config={"fin_contrat": st.column_config.DateColumn("Fin de contrat", format="DD/MM/YYYY")})
        if st.button("💾 Enregistrer les prestataires", key="pr_ok"):
            gc.sauver("gmao_prestataires", ed.dropna(subset=["nom"]), "liste des prestataires modifiée")
            ok("Prestataires enregistrés.")


# ============================================================================= BUDGETS
def module_budgets():
    annee = st.selectbox("Exercice", list(range(auj.year - 2, auj.year + 3)), index=2, key="bud_an")
    bud = gc.table("gmao_budget")
    b_an = bud[bud["annee"] == annee]
    base = pd.DataFrame({"poste": gc.POSTES_BUDGET})
    base["montant_prevu"] = base["poste"].map(dict(zip(b_an["poste"], b_an["montant_prevu"]))).fillna(0.0)
    c1, c2 = st.columns([2, 3])
    with c1:
        st.markdown(f"**Budget de maintenance {annee}**")
        ed = st.data_editor(base, hide_index=True, width="stretch", key=f"bud_ed_{annee}", disabled=["poste"],
                            column_config={"montant_prevu": st.column_config.NumberColumn("Montant prévu (FCFA)", format="localized")})
        if st.button("💾 Enregistrer le budget", key="bud_ok"):
            gc.sauver("gmao_budget", pd.concat([bud[bud["annee"] != annee], ed.assign(annee=annee)], ignore_index=True),
                      f"budget de maintenance {annee}")
            ok(f"Budget {annee} enregistré.")
    with c2:
        ex = gc.execution_budget(annee)
        st.markdown("**Exécution**")
        st.dataframe(ex, hide_index=True, width="stretch",
                     column_config={c: st.column_config.NumberColumn(format="localized") for c in
                                    ["Budget prévu", "Engagé (commandes)", "Réalisé (BI)", "Disponible"]})
        fig = go.Figure()
        fig.add_bar(x=ex["Poste"], y=ex["Budget prévu"], name="Prévu", marker_color=GREY)
        fig.add_bar(x=ex["Poste"], y=ex["Engagé (commandes)"], name="Engagé", marker_color=GOLD)
        fig.add_bar(x=ex["Poste"], y=ex["Réalisé (BI)"], name="Réalisé", marker_color=NAVY)
        fig.update_layout(barmode="group")
        st.plotly_chart(_fig(fig, height=320), width="stretch")
    b = gc.couts_bi(bi)
    b = b[b["date_fin"].dt.year == annee]
    if b["cout_total"].sum():
        c1, c2 = st.columns(2)
        with c1:
            top = b.groupby("site")["cout_total"].sum().sort_values(ascending=False).head(15).reset_index()
            fig = px.bar(top, x="cout_total", y="site", orientation="h", color_discrete_sequence=[NAVY],
                         title="Coût de maintenance par centrale", labels={"cout_total": "FCFA", "site": ""})
            fig.update_yaxes(categoryorder="total ascending")
            st.plotly_chart(_fig(fig, height=420, legend=False), width="stretch")
        with c2:
            fig = px.pie(b, names="type", values="cout_total", hole=0.45, title="Coût par type de maintenance")
            st.plotly_chart(_fig(fig, height=420), width="stretch")


# ============================================================================= ANALYSES
def module_analyses():
    t1, t2 = st.tabs(["🧾 Interventions (BI)", "📜 Journaux de maintenance 2025-2026"])
    with t1:
        if bi.empty:
            st.info("Aucun bon d'intervention : les analyses des journaux sont dans l'onglet voisin.")
        else:
            c1, c2, c3 = st.columns(3)
            dmin = (bi["date_creation"].min() if bi["date_creation"].notna().any() else auj).date()
            per = c1.date_input("Période", (dmin, auj.date()), key="an_per", format="DD/MM/YYYY")
            ft = c2.multiselect("Type", gc.TYPES_BI, key="an_t")
            fp = c3.multiselect("Phase", sorted(ref["Phase"].unique()), key="an_p")
            v = bi.copy()
            if isinstance(per, tuple) and len(per) == 2:
                d0, d1 = pd.Timestamp(per[0]), pd.Timestamp(per[1]) + pd.Timedelta(days=1)
                v = v[v["date_creation"].between(d0, d1) | v["date_creation"].isna()]
            else:
                d0, d1 = pd.Timestamp(dmin), auj + pd.Timedelta(days=1)
            if ft:
                v = v[v["type"].isin(ft)]
            if fp:
                v = v[v["phase"].isin(fp)]
            k = gc.kpis_bi(v, auj)
            f = lambda x, d=1: "—" if x is None or pd.isna(x) else f"{x:,.{d}f}".replace(",", " ").replace(".", ",")
            kpi_row([("BI", f(k["total"], 0), None), ("Ouverts / en retard", f"{k['ouverts']} / {k['en_retard']}", None),
                     ("Part du préventif", f"{f(k['part_preventif'])} %", None),
                     ("MTTR (temps d'arrêt moyen)", f"{f(k['mttr_h'])} h", None),
                     ("Respect du planning", f"{f(k['respect_planning'])} %", None)])
            c1, c2 = st.columns(2)
            with c1:
                fig = px.histogram(v, x="statut", color="type", barmode="stack", title="BI par statut et par type",
                                   category_orders={"statut": gc.STATUTS_BI})
                st.plotly_chart(_fig(fig, height=340), width="stretch")
            with c2:
                fig = px.histogram(v, y="systeme", color="priorite", title="BI par système et par priorité")
                fig.update_yaxes(categoryorder="total ascending")
                st.plotly_chart(_fig(fig, height=340), width="stretch")
            v["mois"] = v["date_creation"].dt.to_period("M").dt.to_timestamp()
            ev = v.groupby(["mois", "type"]).size().reset_index(name="BI")
            fig = px.bar(ev, x="mois", y="BI", color="type", title="BI créés par mois", labels={"mois": ""})
            st.plotly_chart(_fig(fig, height=300), width="stretch")
            dispo = gc.disponibilite_sites(v, d0, d1)
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Disponibilité des centrales sur la période (arrêts déclarés en BI)**")
                st.dataframe(dispo, hide_index=True, width="stretch", height=320)
            with c2:
                cb = gc.couts_bi(v)
                st.markdown("**Coûts par système**")
                st.dataframe(cb.groupby("systeme")[["cout_mo", "cout_presta", "cout_pieces", "cout_total"]].sum().round(0),
                             width="stretch")
                ca = v["cause"].dropna()
                if len(ca):
                    fig = px.pie(ca.value_counts().reset_index(), names="cause", values="count", hole=0.45,
                                 title="Causes des défaillances")
                    st.plotly_chart(_fig(fig, height=300), width="stretch")
    with t2:
        gmao_ui.tableau_de_bord(pd.DataFrame(), ref)


# ============================================================================= MODE TERRAIN
def module_terrain():
    st.caption("Écran simplifié pour téléphone : ouvre cette page dans le navigateur du téléphone (même adresse que "
               "l'application), puis ajoute-la à l'écran d'accueil.")
    action = st.radio("Que veux-tu faire ?", ["🚨 Signaler une panne", "🧾 Mes interventions", "🔩 Sortir une pièce"],
                      key="te_act")
    if action.startswith("🚨"):
        formulaire_di("te")
    elif action.startswith("🧾"):
        chefs = sorted(bi["chef"].dropna().astype(str).unique())
        moi = st.selectbox("Je suis", chefs, index=None, placeholder="Choisir mon nom…", key="te_moi")
        mes = bi[bi["statut"].isin(gc.STATUTS_BI_OUVERTS) & ((bi["chef"] == moi) if moi else True)]
        st.caption(f"{len(mes)} intervention(s) ouverte(s)")
        for _, b in mes.sort_values("date_prevue").head(30).iterrows():
            with st.container(border=True):
                st.markdown(f"**{b['site']}** — {b['type']} · {b['priorite']}  \n{str(b['description'] or '')[:120]}  \n"
                            f"📅 {b['date_prevue']:%d/%m/%Y}" if pd.notna(b["date_prevue"]) else f"**{b['site']}** — {b['type']}")
                c1, c2 = st.columns(2)
                if c1.button("▶️ Démarrer", key=f"te_go_{b['id']}", disabled=b["statut"] == "En cours", width="stretch"):
                    gc.modifier("gmao_bi", b["id"], {"statut": "En cours", "date_debut": pd.Timestamp(gc.maintenant())},
                                f"{b['id']} démarré (terrain)")
                    ok(f"{b['id']} démarré.")
                if c2.button("✅ Terminer", key=f"te_fin_{b['id']}", width="stretch"):
                    gc.modifier("gmao_bi", b["id"], {"statut": "Terminé", "date_fin": pd.Timestamp(gc.maintenant())},
                                f"{b['id']} terminé (terrain)")
                    ok(f"{b['id']} terminé — à clôturer au bureau (coûts, temps d'arrêt).")
    else:
        niv = gc.niveaux_stock()
        if niv.empty:
            st.info("Catalogue vide.")
        else:
            code = st.selectbox("Pièce", niv["code"], format_func=lambda c: f"{c} — {niv.set_index('code').at[c, 'designation']}",
                                key="te_art")
            q = st.number_input("Quantité", 1.0, 10000.0, 1.0, key="te_q")
            bid = st.selectbox("Pour le BI", bi.loc[bi["statut"].isin(gc.STATUTS_BI_OUVERTS), "id"], index=None, key="te_bi")
            if st.button("➖ Sortir", type="primary", width="stretch", key="te_out", disabled=not bid):
                gc.ajouter("gmao_mouvements", [{"date": pd.Timestamp(gc.maintenant()), "code": code, "type": "Sortie",
                                                "quantite": q, "bi_id": bid, "motif": "Sortie terrain"}], "MV",
                           f"sortie terrain {code} × {q:g} ({bid})")
                ok("Sortie enregistrée.")


# ============================================================================= PARAMÈTRES
def module_parametres():
    t1, t2 = st.tabs(["📥 Journaux de maintenance", "⬇️ Exports"])
    with t1:
        gmao_ui.ecran_import()
    with t2:
        st.caption("Export de toutes les tables GMAO dans un classeur Excel (une feuille par table).")
        if st.button("Préparer l'export", key="par_exp"):
            buf = io.BytesIO()
            with pd.ExcelWriter(buf) as xw:
                for nom in gc.COLS:
                    gc.table(nom).to_excel(xw, sheet_name=nom.replace("gmao_", "")[:31], index=False)
                for k, v in tables_j.items():
                    if v is not None and len(v):
                        v.to_excel(xw, sheet_name=f"journal_{k}"[:31], index=False)
            st.download_button("⬇️ Télécharger", buf.getvalue(), f"gmao_aer_{auj:%Y%m%d}.xlsx", key="par_dl")


{"accueil": accueil, "equipements": module_equipements, "di": module_di, "bi": module_bi, "planning": module_planning,
 "stocks": module_stocks, "achats": module_achats, "ressources": module_ressources, "budgets": module_budgets,
 "analyses": module_analyses, "terrain": module_terrain, "parametres": module_parametres}[mod]()

render_sidebar_footer(data.generated_on)
