"""Suivi de la maintenance — onglets « Parc de sites », « Backlog » et « Nouvelle fiche » (interface).
Les calculs sont dans gmao_indicateurs.py (fonctions pures) et les lectures / écritures dans gmao_suivi.py."""
from __future__ import annotations

import io

import pandas as pd
import plotly.express as px
import streamlit as st

from . import gmao as g
from . import gmao_core as gc
from . import gmao_indicateurs as gi
from . import gmao_suivi as gs
from .auth import peut_modifier
from .ui import kpi_row, plotly_base_layout, section_title

COULEURS_GROUPE = {"En service H24": "#16A34A", "Service partiel": "#D97706", "À l'arrêt": "#DC2626",
                   gi.NON_MES: "#9CA3AF", gi.NON_RENSEIGNE: "#D1D5DB"}
PASTILLE = {gi.H24: "🟢", gi.A_VIDE: "🔵", gi.AVANT_18H: "🟠", gi.APRES_18H: "🟠", gi.PARTIEL_AUTRE: "🟠", gi.ARRET: "🔴",
            gi.NON_MES: "⚪", gi.NON_RENSEIGNE: "⚪"}
PASTILLE_PRIO = {"URGENT": "🟥", "CRITIQUE": "🟧", "MAJEUR": "🟨", "MINEUR": "🟦", "Non renseignée": "⬜"}
LIMITE_BACKLOG = 300
DATE = {"format": "DD/MM/YYYY"}


def n(x, dec: int = 0, suffixe: str = "") -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"{x:,.{dec}f}".replace(",", " ").replace(".", ",") + suffixe


def _flash(cle: str) -> None:
    if st.session_state.get(cle):
        st.success("💾 " + st.session_state.pop(cle))


def _ok(cle: str, msg: str) -> None:
    st.session_state[cle] = msg
    st.rerun()


def _erreurs(e: ValueError) -> None:
    st.error("Enregistrement refusé :\n\n- " + "\n- ".join(str(e).split("\n")))


# ============================================================================= PARC DE SITES
def onglet_parc(sites: pd.DataFrame, f: pd.DataFrame, arrets: pd.DataFrame, visites: pd.DataFrame, ref: pd.DataFrame,
                auj: pd.Timestamp) -> None:
    _flash("_smp_ok")
    c = st.columns([2, 1.2, 1.2, 1.4, 1.2])
    q = c[0].text_input("Rechercher une centrale", key="smp_q", placeholder="Nom de la centrale…")
    f_reg = c[1].multiselect("Région", sorted(sites["region"].dropna().unique()), key="smp_reg")
    f_zone = c[2].multiselect("Zone", sorted(sites["zone"].dropna().unique()), key="smp_zone")
    f_etat = c[3].multiselect("État", gi.GROUPES, key="smp_etat")
    f_ph = c[4].multiselect("Phase", sorted(sites["phase"].dropna().unique()), key="smp_ph")
    s = sites
    for col, val in (("region", f_reg), ("zone", f_zone), ("phase", f_ph)):
        if val:
            s = s[s[col].isin(val)]
    if f_etat:
        s = s[s["etat"].map(gi.GROUPE).isin(f_etat)]
    if q.strip():
        s = s[s["site"].astype(str).str.contains(q.strip(), case=False, regex=False)]
    if s.empty:
        st.warning("Aucune centrale ne correspond à la sélection.")
        return
    cles = set(s["cle_site"])
    fs = f[f["cle_site"].isin(cles)]
    pu = gi.puissance_parc(s)
    gr = s["etat"].map(gi.GROUPE)
    ouv = fs[fs["ouvert"]]
    a_an = arrets[(arrets["date"].dt.year == auj.year) & arrets["cle_site"].isin(cles)]
    v_s = visites[visites["cle_site"].isin(cles)]
    par_phase = " · ".join(f"{p.replace('Phase ', 'Ph')} : {k}" for p, k in s.groupby("phase").size().items())
    kpi_row([
        ("Sites sélectionnés", n(len(s)), par_phase),
        ("Puissance installée", n(pu["installee"], suffixe=" kWc"), f"dont {n(pu['non_mes'])} kWc non mise en service"),
        ("Puissance en service", n(pu["en_service"], suffixe=" kWc"),
         f"{n(100 * pu['en_service'] / (pu['installee'] - pu['non_mes']) if pu['installee'] > pu['non_mes'] else None)} % exploité"),
        ("H24 / partiel / arrêt", f"{int((gr == 'En service H24').sum())} / {int((gr == 'Service partiel').sum())} / {pu['sites_arret']}",
         f"{pu['sites_non_mes']} non mis en service"),
        ("Défauts ouverts", n(len(ouv)), f"{int(ouv['hors_delai'].sum())} hors délai"),
        (f"Arrêts {auj.year}", n(len(a_an)), f"{a_an['cle_site'].nunique()} sites concernés"),
        ("Sites déjà visités", n(v_s["cle_site"].nunique()),
         f"{v_s.loc[v_s['date'].dt.year == auj.year, 'cle_site'].nunique()} en {auj.year} · {len(s) - v_s['cle_site'].nunique()} jamais"),
    ])
    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown("**Répartition de la sélection par région**")
        st.dataframe(gi.synthese_par_region(s, fs), hide_index=True, width="stretch",
                     column_config={"Installée (kWc)": st.column_config.NumberColumn(format="%.0f"),
                                    "En service (kWc)": st.column_config.NumberColumn(format="%.0f"),
                                    "% exploité": st.column_config.ProgressColumn("% exploité", format="%.0f %%", min_value=0, max_value=100)})
    with c2:
        d = gr.value_counts().reindex(gi.GROUPES).dropna().reset_index()
        d.columns = ["État", "Centrales"]
        fig = px.pie(d, names="État", values="Centrales", hole=0.55, color="État", color_discrete_map=COULEURS_GROUPE,
                     title="État de la sélection")
        fig.update_traces(sort=False, textinfo="value")
        fig = plotly_base_layout(fig, height=300)
        fig.update_layout(legend=dict(orientation="h", y=-0.15), margin=dict(t=40))
        st.plotly_chart(fig, width="stretch")

    section_title("CENTRALES")
    t = gi.table_sites(s, f, arrets, visites, auj.year)
    t["État"] = t["État"].map(lambda e: f"{PASTILLE.get(e, '')} {e}")
    st.caption(f"{len(t)} centrale(s). L'identifiant officiel (PH1-001…) et le programme de réhabilitation ne sont pas "
               "dans les données de l'application : colonnes à compléter quand le référentiel sera fourni.")
    st.dataframe(t.drop(columns="cle_site"), hide_index=True, width="stretch", height=420,
                 column_config={"Dernière visite": st.column_config.DateColumn(**DATE), "Dernier défaut": st.column_config.DateColumn(**DATE),
                                "État constaté le": st.column_config.DateColumn(**DATE),
                                "Cause / observation": st.column_config.TextColumn(width="medium")})
    buf = io.BytesIO()
    t.drop(columns="cle_site").to_excel(buf, index=False)
    st.download_button("⬇️ Exporter la liste (Excel)", buf.getvalue(), "parc_de_sites.xlsx", key="smp_dl")

    # ---- fiche d'une centrale et saisie de son état
    section_title("FICHE D'UNE CENTRALE ET MISE À JOUR DE SON ÉTAT")
    lib = dict(zip(s["cle_site"], s["site"] + " (" + s["phase"].astype(str) + ", " + s["region"].astype(str) + ")"))
    k = st.selectbox("Centrale", list(lib), format_func=lib.get, index=None, key="smp_site", placeholder="Choisir une centrale…")
    if not k:
        return
    r = s.set_index("cle_site").loc[k]
    info = ref.assign(_k=ref["Nom du site"].map(g.cle)).drop_duplicates("_k").set_index("_k")
    lieu = f"{info.at[k, 'Département']} / {info.at[k, 'Arrondissement']}" if k in info.index and "Département" in info else "—"
    c1, c2 = st.columns([3, 2])
    with c1:
        depuis = "" if pd.isna(r["etat_date"]) else f" depuis le {r['etat_date']:%d/%m/%Y}"
        st.markdown(f"""**{r['site']}** — {r['phase']} · {r['region']} ({lieu}) · {n(r['kwc'], 1)} kWc
- État : {PASTILLE.get(r['etat'], '')} **{r['etat']}**{depuis} — source : {r['etat_source'].lower()}
- Cause / observation : {r['cause'] if not gi.est_vide(r['cause']) else '—'}
- Zone : {r['zone'] or '—'} · Responsable : {r['responsable'] or '—'}""")
        fk = f[f["cle_site"] == k].sort_values("date_constat", ascending=False)
        st.markdown(f"**Fiches : {len(fk)}** — {int(fk['ouvert'].sum())} ouverte(s), {int(fk['hors_delai'].sum())} hors délai")
        if len(fk):
            st.dataframe(_vue_fiches(fk).drop(columns=["Site", "Zone"], errors="ignore"), hide_index=True, width="stretch", height=260,
                         column_config={"Constat": st.column_config.DateColumn(**DATE), "Échéance": st.column_config.DateColumn(**DATE),
                                        "Description": st.column_config.TextColumn(width="large")})
        es = gs.etats_saisis()
        es = es[es["cle_site"] == k].sort_values(["date_effet", "horodatage"], ascending=False)
        if len(es):
            st.markdown("**Historique des états saisis**")
            st.dataframe(es[["date_effet", "etat", "cause", "commentaire", "auteur", "horodatage"]].rename(columns={
                "date_effet": "Constaté le", "etat": "État", "cause": "Cause", "commentaire": "Commentaire",
                "auteur": "Saisi par", "horodatage": "Saisi le"}), hide_index=True, width="stretch",
                column_config={"Constaté le": st.column_config.DateColumn(**DATE),
                               "Saisi le": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm")})
    with c2:
        if not peut_modifier():
            st.info("🔒 Votre profil ne permet pas de modifier l'état d'une centrale.")
            return
        v = st.session_state.get("_smp_n", 0)
        with st.form(f"smp_etat_{k}_{v}"):
            st.markdown("**Mettre à jour l'état de la centrale**")
            etat = st.selectbox("État constaté", gi.ETATS_SAISIE, key=f"smp_e_{k}_{v}",
                                index=gi.ETATS_SAISIE.index(r["etat"]) if r["etat"] in gi.ETATS_SAISIE else None,
                                format_func=lambda e: f"{PASTILLE.get(e, '')} {e}")
            causes = gs.reglage("causes_arret", gi.CAUSES_ARRET_DEFAUT)
            cause = st.selectbox("Cause (obligatoire si arrêt ou service partiel)", causes, index=None, accept_new_options=True,
                                 key=f"smp_c_{k}_{v}", placeholder="Choisir ou saisir une cause")
            quand = st.date_input("Constaté le", value=auj.date(), max_value=auj.date(), key=f"smp_d_{k}_{v}", format="DD/MM/YYYY")
            com = st.text_input("Commentaire", key=f"smp_com_{k}_{v}")
            if st.form_submit_button("💾 Enregistrer l'état", type="primary"):
                try:
                    if gs.enregistrer_etat(r["site"], etat, cause, quand, com, auj):
                        st.session_state["_smp_n"] = v + 1
                        _ok("_smp_ok", f"État de {r['site']} enregistré : {etat} au {pd.Timestamp(quand):%d/%m/%Y}.")
                except ValueError as e:
                    _erreurs(e)
        st.caption("L'état saisi remplace celui du journal pour cette centrale, ici et dans le GMAO. L'historique des "
                   "saisies est conservé. « Fonctionne à vide » : la centrale tourne mais le réseau de distribution "
                   "n'est pas disponible.")


# ============================================================================= BACKLOG
def _vue_fiches(b: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "Priorité": b["priorite"].map(lambda p: f"{PASTILLE_PRIO.get(p, '')} {p}"), "Constat": b["date_constat"],
        "Échéance": b["echeance"], "Retard (j)": b["retard_j"], "Site": b["site"],
        "Zone": b["zone"] if "zone" in b else None, "Catégorie": b["categorie"], "Matériel": b["materiel"],
        "Description": b["description"], "Statut": b["ouvert"].map({True: "Ouvert", False: "Clôturé"}),
        "Source": b["source"], "Réf.": b["ref"]})


def onglet_backlog(sites: pd.DataFrame, f: pd.DataFrame, auj: pd.Timestamp) -> None:
    _flash("_smb_ok")
    zone = dict(zip(sites["cle_site"], sites["zone"]))
    c = st.columns([2, 1.2, 1, 1.2, 1.6, 1.1])
    q = c[0].text_input("Rechercher", key="smb_q", placeholder="Site, description, matériel…")
    f_reg = c[1].multiselect("Région", sorted(f["region"].dropna().unique()), key="smb_reg")
    f_zone = c[2].multiselect("Zone", sorted({z for z in zone.values() if isinstance(z, str)}), key="smb_zone")
    f_prio = c[3].multiselect("Priorité", gi.PRIORITES, key="smb_prio")
    f_cat = c[4].multiselect("Catégorie", sorted(f["categorie"].dropna().unique()), key="smb_cat")
    f_del = c[5].selectbox("Délai", gi.FILTRES_DELAI, key="smb_del")
    b = gi.backlog(f, q, f_reg, f_zone, f_prio, f_cat, f_del, zone)
    total, retard = len(b), int(b["hors_delai"].sum())
    c1, c2 = st.columns([3, 1])
    c1.markdown(f"**{n(total)} fiche(s) ouverte(s)** dont **{n(retard)} hors délai**"
                + (f" — les {LIMITE_BACKLOG} premières sont affichées ; l'export les contient toutes." if total > LIMITE_BACKLOG else ""))
    vue = _vue_fiches(b)
    c2.download_button("⬇️ Exporter (CSV)", vue.to_csv(index=False, sep=";", date_format="%d/%m/%Y").encode("utf-8-sig"),
                       "backlog_maintenance.csv", "text/csv", key="smb_dl", disabled=b.empty)
    if b.empty:
        st.success("Aucune fiche ouverte pour cette sélection.")
        return
    st.dataframe(vue.head(LIMITE_BACKLOG), hide_index=True, width="stretch", height=430,
                 column_config={"Constat": st.column_config.DateColumn(**DATE), "Échéance": st.column_config.DateColumn(**DATE),
                                "Retard (j)": st.column_config.NumberColumn(format="%d j"),
                                "Description": st.column_config.TextColumn(width="large")})
    sans_date, sans_ech = int(b["date_constat"].isna().sum()), int(b["echeance"].isna().sum())
    if sans_date or sans_ech:
        st.caption(f"{sans_ech} fiche(s) sans échéance (délai de leur priorité non paramétré, ou date de constat absente), "
                   f"dont {sans_date} sans date de constat : elles sont listées en fin de leur priorité et ne peuvent "
                   "pas être « hors délai ».")

    # ---- mise à jour d'une fiche
    section_title("METTRE À JOUR UNE FICHE")
    if not peut_modifier():
        st.info("🔒 Votre profil ne permet pas de mettre à jour une fiche.")
        return
    b2 = b.head(LIMITE_BACKLOG)
    lib = {i: f"{r.priorite} · {'sans date' if pd.isna(r.date_constat) else r.date_constat.strftime('%d/%m/%Y')} · {r.site} · "
              f"{r.materiel} · {str(r.description)[:60]}" for i, r in zip(b2.index, b2.itertuples())}
    i = st.selectbox("Fiche (parmi celles affichées)", list(lib), format_func=lib.get, index=None, key="smb_sel",
                     placeholder="Choisir une fiche à mettre à jour…")
    if i is None:
        return
    r = b2.loc[i]
    journal = r["source"] != "Application"
    st.caption(f"{r['source']} {r['ref'] or ''} — {r['site']} — {r['categorie']} — quantité affectée : {n(r['qte_affectee'])} — "
               f"déjà remplacée : {n(r['qte_remplacee'])}")
    with st.form(f"smb_maj_{i}"):
        c = st.columns([1.3, 1, 1.2, 3])
        if journal:
            statut = c[0].selectbox("Statut", ["Ouvert", "Clôturé"], key=f"smb_st_{i}")
        else:
            bi = gc.table("gmao_bi")
            actuel = bi.loc[bi["id"].astype(str) == str(r["ref"]), "statut"]
            statut = c[0].selectbox("Statut", [x for x in gc.STATUTS_BI if x != "Annulé"], key=f"smb_st_{i}",
                                    index=gc.STATUTS_BI.index(actuel.iloc[0]) if len(actuel) and actuel.iloc[0] in gc.STATUTS_BI else 0)
        qr = c[1].number_input("Quantité remplacée (total)", min_value=0.0, step=1.0, value=float(r["qte_remplacee"] or 0), key=f"smb_qr_{i}")
        dc = c[2].date_input("Date de clôture", value=auj.date(), max_value=auj.date(), key=f"smb_dc_{i}", format="DD/MM/YYYY",
                             help="Prise en compte seulement si la fiche est clôturée.")
        mes = c[3].text_input("Mesure prise", key=f"smb_mes_{i}")
        if st.form_submit_button("💾 Mettre à jour la fiche", type="primary"):
            try:
                if journal:
                    gs.maj_fiche_journal(int(r["ligne"]), r["site"], statut == "Clôturé", qr, mes, dc, auj)
                else:
                    gs.maj_fiche_application(r["ref"], statut, qr, mes, dc, auj)
                _ok("_smb_ok", f"Fiche mise à jour ({r['site']} — {r['materiel']}) : {statut.lower()}.")
            except ValueError as e:
                _erreurs(e)
    if journal:
        st.caption("⚠️ Cette fiche vient d'un journal importé : la mise à jour est enregistrée dans la base, mais "
                   "réimporter ce même journal (GMAO → Paramètres & imports) la remplacerait par le contenu du fichier.")


# ============================================================================= NOUVELLE FICHE
def onglet_fiche(sites: pd.DataFrame, ref: pd.DataFrame, auj: pd.Timestamp, equipes: list[str],
                 materiels_connus: list[str] | None = None) -> None:
    _flash("_smf_ok")
    if not peut_modifier():
        st.info("🔒 Votre profil ne permet pas de créer une fiche.")
        return
    st.caption("Une fiche de défaut est un bon d'intervention correctif du GMAO, enrichi du matériel et des quantités : "
               "elle apparaît aussi dans « GMAO — Maintenance → Bons d'intervention », où se gèrent pièces sorties et coûts.")
    info = ref.assign(_k=ref["Nom du site"].map(g.cle)).drop_duplicates("_k").set_index("_k")
    s = sites[sites["cle_site"].isin(info.index)].sort_values("site")
    lib = dict(zip(s["cle_site"], s["site"] + " (" + s["phase"].astype(str) + ", " + s["region"].astype(str) + ")"))
    delais = gs.delais()
    v = st.session_state.get("_smf_n", 0)
    # la priorité est hors formulaire : le délai et l'échéance se recalculent dès qu'elle change
    c = st.columns(6)
    k = c[0].selectbox("Site *", list(lib), format_func=lib.get, index=None, key=f"smf_site_{v}", placeholder="Nom de la centrale…")
    constat = c[1].date_input("Date de constat *", value=auj.date(), max_value=auj.date(), key=f"smf_date_{v}", format="DD/MM/YYYY")
    prio = c[2].selectbox("Priorité *", list(gi.PRIORITE_VERS_BI), key=f"smf_prio_{v}", format_func=lambda p: f"{PASTILLE_PRIO[p]} {p}")
    d_auto = gi.delai_resolution(prio, delais)
    jours = d_auto
    if d_auto is None:
        jours = c[3].number_input("Délai de résolution (jours)", min_value=0, step=1, value=None, key=f"smf_j_{v}_{prio}",
                                  help=f"Aucun délai n'est paramétré pour la priorité {prio} : saisis-le, ou laisse vide "
                                       "(la fiche n'aura pas d'échéance).")
    else:
        c[3].text_input("Délai de résolution (auto)", value=f"{d_auto} jour(s)", disabled=True, key=f"smf_ja_{v}_{prio}")
    ech = gi.echeance(pd.Timestamp(constat), prio, delais, jours)
    c[4].text_input("Échéance (auto)", value="—" if ech is None else f"{ech:%d/%m/%Y}", disabled=True, key=f"smf_ech_{v}_{prio}_{constat}_{jours}")
    statut = c[5].selectbox("Statut", ["Ouvert", "En cours", "Clôturé"], key=f"smf_st_{v}")
    with st.form(f"smf_{v}"):
        c = st.columns(6)
        arrivee = c[0].selectbox("État du site à l'arrivée *", gi.ETATS_ARRIVEE, key=f"smf_arr_{v}")
        cat = c[1].selectbox("Catégorie *", gc.SYSTEMES, index=None, key=f"smf_cat_{v}", placeholder="Choisir…")
        # libellés déjà employés (catalogue des articles et journaux) : on évite ainsi les variantes d'un même matériel
        materiels = sorted({str(x).strip() for x in list(gc.table("gmao_articles")["designation"].dropna()) + list(materiels_connus or [])
                            if not gi.est_vide(x)}, key=str.lower)
        mat = c[2].selectbox("Matériel affecté *", materiels, index=None, accept_new_options=True, key=f"smf_mat_{v}",
                             placeholder="Choisir ou saisir…")
        qa = c[3].number_input("Quantité affectée", min_value=0.0, step=1.0, value=0.0, key=f"smf_qa_{v}")
        qr = c[4].number_input("Quantité remplacée", min_value=0.0, step=1.0, value=0.0, key=f"smf_qr_{v}")
        equipe = c[5].selectbox("Technicien / équipe", equipes, index=None, accept_new_options=True, key=f"smf_eq_{v}",
                                placeholder="Choisir ou saisir…")
        desc = st.text_area("Description du problème *", key=f"smf_desc_{v}", height=80)
        mesure = st.text_area("Mesure prise", key=f"smf_mes_{v}", height=70)
        c = st.columns([2, 3])
        dcl = c[0].date_input("Date de clôture (si la fiche est clôturée)", value=auj.date(), max_value=auj.date(), key=f"smf_dcl_{v}",
                              format="DD/MM/YYYY")
        c[1].caption("Un état « À l'arrêt » à l'arrivée marque le bon d'intervention « centrale à l'arrêt » : la centrale "
                     "passe à l'arrêt dans l'application tant que la fiche est ouverte. La déclaration d'un épisode "
                     "d'arrêt daté (avec remise en marche) arrive avec l'onglet « Arrêts et disponibilité ».")
        if st.form_submit_button("💾 Enregistrer la fiche", type="primary"):
            try:
                r = s.set_index("cle_site").loc[k] if k else None
                ident = gs.creer_fiche({
                    "site": None if r is None else r["site"], "site_id": None if r is None else info.at[k, "site_id"],
                    "phase": None if r is None else r["phase"], "region": None if r is None else r["region"],
                    "date_constat": pd.Timestamp(constat), "priorite": prio, "jours_prevus": jours, "categorie": cat,
                    "materiel": mat, "description": desc, "qte_affectee": qa, "qte_remplacee": qr, "etat_arrivee": arrivee,
                    "statut": {"Ouvert": "À planifier", "En cours": "En cours"}.get(statut), "cloturee": statut == "Clôturé",
                    "date_cloture": pd.Timestamp(dcl), "equipe": equipe, "mesure_prise": mesure}, auj)
                st.session_state["_smf_n"] = v + 1
                _ok("_smf_ok", f"Fiche {ident} enregistrée pour {r['site']}"
                    + ("." if ech is None else f" — échéance le {ech:%d/%m/%Y}."))
            except ValueError as e:
                _erreurs(e)
