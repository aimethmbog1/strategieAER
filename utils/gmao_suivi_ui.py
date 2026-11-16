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
        cause_arret = c[1].selectbox("Cause de l'arrêt (si un arrêt est déclaré)", gs.reglage("causes_arret", gi.CAUSES_ARRET_DEFAUT),
                                     index=None, accept_new_options=True, key=f"smf_ca_{v}", placeholder="Non précisée")
        arret_aussi = st.checkbox("Déclarer aussi un arrêt du site (alimente le calcul de disponibilité)", key=f"smf_arret_{v}",
                                  help="Ouvre un épisode d'arrêt à la date de constat. Il sera clos à la clôture de la fiche, "
                                       "ou par une remise en marche dans « Arrêts et disponibilité ».")
        if st.form_submit_button("💾 Enregistrer la fiche", type="primary"):
            try:
                r = s.set_index("cle_site").loc[k] if k else None
                ident = gs.creer_fiche({
                    "site": None if r is None else r["site"], "site_id": None if r is None else info.at[k, "site_id"],
                    "phase": None if r is None else r["phase"], "region": None if r is None else r["region"],
                    "date_constat": pd.Timestamp(constat), "priorite": prio, "jours_prevus": jours, "categorie": cat,
                    "materiel": mat, "description": desc, "qte_affectee": qa, "qte_remplacee": qr, "etat_arrivee": arrivee,
                    "statut": {"Ouvert": "À planifier", "En cours": "En cours"}.get(statut), "cloturee": statut == "Clôturé",
                    "date_cloture": pd.Timestamp(dcl), "equipe": equipe, "mesure_prise": mesure,
                    "declarer_arret": arret_aussi, "cause_arret": cause_arret}, auj)
                st.session_state["_smf_n"] = v + 1
                _ok("_smf_ok", f"Fiche {ident} enregistrée pour {r['site']}"
                    + ("." if ech is None else f" — échéance le {ech:%d/%m/%Y}."))
            except ValueError as e:
                _erreurs(e)


# ============================================================================= ARRÊTS ET DISPONIBILITÉ
def onglet_arrets(sites: pd.DataFrame, occurrences: pd.DataFrame, equipes: list[str]) -> None:
    _flash("_sma_ok")
    maintenant = pd.Timestamp(gc.maintenant())
    ep = gs.arrets_declares()
    perimetre = set(sites.loc[sites["etat"].map(gi.GROUPE).isin(["En service H24", "Service partiel", "À l'arrêt"]), "cle_site"])
    sans_ep = gs.a_l_arret_sans_episode(sites)
    avec_verif = gs.reglage("arrets_a_verifier_comptes", False)
    infos = sites.drop_duplicates("cle_site").set_index("cle_site")
    edition = peut_modifier()

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Déclarer un arrêt de site**")
        if not edition:
            st.info("🔒 Votre profil ne permet pas de déclarer un arrêt.")
        else:
            v = st.session_state.get("_sma_n", 0)
            s = sites[sites["cle_site"].isin(perimetre)].sort_values("site")
            lib = dict(zip(s["cle_site"], s["site"] + " (" + s["phase"].astype(str) + ", " + s["region"].astype(str) + ")"))
            with st.form(f"sma_new_{v}"):
                k = st.selectbox("Site *", list(lib), format_func=lib.get, index=None, key=f"sma_site_{v}", placeholder="Nom de la centrale…")
                c = st.columns(2)
                jour = c[0].date_input("Début de l'arrêt — date *", value=maintenant.date(), max_value=maintenant.date(), key=f"sma_j_{v}", format="DD/MM/YYYY")
                heure = c[1].time_input("Heure (Douala) *", value=maintenant.time().replace(second=0, microsecond=0), key=f"sma_h_{v}", step=60)
                c = st.columns(2)
                cause = c[0].selectbox("Cause *", gs.reglage("causes_arret", gi.CAUSES_ARRET_DEFAUT), index=None, accept_new_options=True,
                                       key=f"sma_c_{v}", placeholder="Choisir ou saisir…")
                equipe = c[1].selectbox("Équipe intervenante", equipes, index=None, accept_new_options=True, key=f"sma_eq_{v}",
                                        placeholder="Facultatif")
                com = st.text_input("Commentaire", key=f"sma_com_{v}")
                if st.form_submit_button("🛑 Déclarer l'arrêt", type="primary"):
                    try:
                        ident = gs.declarer_arret(None if k is None else infos.at[k, "site"], pd.Timestamp.combine(jour, heure), cause, com, equipe)
                        st.session_state["_sma_n"] = v + 1
                        _ok("_sma_ok", f"Arrêt {ident} déclaré pour {infos.at[k, 'site']} ; la centrale passe « À l'arrêt ».")
                    except ValueError as e:
                        _erreurs(e)
    with c2:
        st.markdown("**Disponibilité du parc**")
        d30 = gi.disponibilite_parc(ep, perimetre, sans_ep, maintenant - pd.Timedelta(days=30), maintenant, avec_verif)
        d90 = gi.disponibilite_parc(ep, perimetre, sans_ep, maintenant - pd.Timedelta(days=90), maintenant, avec_verif)
        enc = gi.arrets_en_cours(ep, maintenant)
        med = gi.duree_mediane_arrets(ep)
        kpi_row([("Disponibilité 30 j", n(d30["disponibilite"], 1, " %"), f"{d30['sites_avec_arret']} sites avec arrêt"),
                 ("Disponibilité 90 j", n(d90["disponibilite"], 1, " %"), f"{d90['sites_avec_arret']} sites avec arrêt"),
                 ("Arrêts en cours", n(len(enc)), f"+ {len(sans_ep & perimetre)} sites à l'arrêt sans arrêt saisi")])
        kpi_row([("Épisodes enregistrés", n(len(ep)), None),
                 ("Durée médiane d'arrêt", n(med["mediane_j"], 1, " j"), f"sur {med['retenus']} arrêt(s) terminé(s)"
                  + (f" ; {med['ecartes']} écarté(s)" if med["ecartes"] else ""))])
        st.caption(f"Calcul : 1 − (durée cumulée des arrêts déclarés ÷ ({len(perimetre)} sites × durée de la période)). Les "
                   f"sites à l'arrêt sans arrêt saisi ({len(sans_ep & perimetre)}) sont comptés indisponibles sur toute la "
                   "période. " + ("Les arrêts terminés à la date de début « à vérifier » sont comptés." if avec_verif else
                                  f"Les arrêts terminés à la date de début « à vérifier » sont écartés ({d90['ecartes_a_verifier']} sur 90 j).")
                   + " Deux arrêts qui se chevauchent sur un même site ne sont comptés qu'une fois.")
        st.warning("⚠️ " + gi.AVERTISSEMENT_DISPONIBILITE)

    # ---- nombre d'arrêts par site
    section_title("NOMBRE D'ARRÊTS PAR SITE")
    annees = sorted({int(a) for a in occurrences["date"].dt.year.dropna().unique()} | {maintenant.year}, reverse=True)
    c = st.columns([1, 1.5, 1.5, 4])
    annee = c[0].selectbox("Année", annees, key="sma_an")
    f_reg = c[1].multiselect("Région", sorted(sites["region"].dropna().unique()), key="sma_reg")
    f_ph = c[2].multiselect("Phase", sorted(sites["phase"].dropna().unique()), key="sma_ph")
    c[3].caption("Occurrences = arrêts déclarés sur la plateforme + fiches et bons d'intervention constatant le site à "
                 "l'arrêt (une seule occurrence par site et par jour).")
    s = sites
    for col, val in (("region", f_reg), ("phase", f_ph)):
        if val:
            s = s[s[col].isin(val)]
    occ = occurrences[occurrences["cle_site"].isin(set(s["cle_site"]))]
    ep_s = ep[ep["cle_site"].isin(set(s["cle_site"]))]
    rouge, orange = "#B91C1C", "#C2410C"

    def fig_(fig, h=300):
        fig = plotly_base_layout(fig, height=h)
        fig.update_layout(separators=", ", legend=dict(orientation="h", y=-0.25), margin=dict(t=40))
        return fig

    c1, c2 = st.columns(2)
    with c1:
        m = gi.arrets_par_mois(occ, annee)
        fig = px.bar(m, x="Mois", y=["Arrêts", "Sites distincts"], barmode="group", title=f"Arrêts par mois — {annee}",
                     color_discrete_map={"Arrêts": rouge, "Sites distincts": orange}, labels={"value": "", "variable": ""})
        st.plotly_chart(fig_(fig), width="stretch")
    with c2:
        a = gi.arrets_par_an(occ)
        if a.empty:
            st.info("Aucune occurrence d'arrêt datée.")
        else:
            fig = px.bar(a.astype({"Année": str}), x="Année", y=["Arrêts", "Sites distincts"], barmode="group", title="Arrêts par an",
                         color_discrete_map={"Arrêts": rouge, "Sites distincts": orange}, labels={"value": "", "variable": ""})
            st.plotly_chart(fig_(fig), width="stretch")
    c1, c2 = st.columns(2)
    with c1:
        if ep_s.empty:
            st.info("Causes des arrêts déclarés : aucun arrêt déclaré sur la plateforme pour cette sélection.")
        else:
            ca = gi.causes_arrets(ep_s).sort_values("Arrêts")
            fig = px.bar(ca, y="Cause", x="Arrêts", orientation="h", title="Causes des arrêts déclarés", color_discrete_sequence=[rouge])
            st.plotly_chart(fig_(fig), width="stretch")
    with c2:
        de = gi.duree_arret_par_equipe(ep_s, maintenant)
        if de.empty:
            st.info("Durée cumulée d'arrêt par équipe : aucun arrêt déclaré n'indique d'équipe intervenante.")
        else:
            fig = px.bar(de, x="Équipe", y="Jours d'arrêt", title="Durée cumulée d'arrêt par équipe intervenante (jours)",
                         color_discrete_sequence=[orange])
            st.plotly_chart(fig_(fig), width="stretch")
    mat = gi.matrice_arrets(occ, s, annee)
    if mat.empty:
        st.info("Aucune occurrence d'arrêt pour cette sélection.")
    else:
        st.caption(f"{len(mat)} site(s) avec au moins une occurrence d'arrêt, du plus au moins touché en {annee}.")
        num = [c_ for c_ in mat.columns if c_ not in ("Site", "Région", "Phase")]
        vue_m = mat.copy()
        vue_m[num] = vue_m[num].astype(object).where(mat[num] != 0, "")       # cases vides plutôt que des zéros
        st.dataframe(vue_m.astype({c_: str for c_ in num}), hide_index=True, width="stretch", height=360)

    # ---- arrêts en cours
    section_title("ARRÊTS EN COURS")
    if enc.empty:
        st.info("Aucun arrêt en cours déclaré sur la plateforme.")
    else:
        vue = pd.DataFrame({
            "N°": enc["id"], "Site": enc["site"], "Région": enc["cle_site"].map(infos["region"]), "Zone": enc["cle_site"].map(infos["zone"]),
            "Depuis": enc["debut"], "Date": enc["date_a_verifier"].map({True: "⚠️ à vérifier", False: ""}),
            "Durée (j)": enc["duree_j"], "Cause": enc["cause"], "Équipe": enc["equipe"], "Source": enc["source"]})
        st.dataframe(vue, hide_index=True, width="stretch",
                     column_config={"Depuis": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm"),
                                    "Durée (j)": st.column_config.NumberColumn(format="%.1f j")})
        if edition:
            lib = {r.id: f"{r.id} — {r.site} — depuis le " + ("date inconnue" if pd.isna(r.debut) else f"{r.debut:%d/%m/%Y %H:%M}")
                   for r in enc.itertuples()}
            with st.form("sma_remise"):
                st.markdown("**Remise en marche**")
                c = st.columns([3, 1.3, 1, 1.6, 1.2])
                ident = c[0].selectbox("Arrêt", list(lib), format_func=lib.get, key="sma_r_id")
                rj = c[1].date_input("Date", value=maintenant.date(), max_value=maintenant.date(), key="sma_r_j", format="DD/MM/YYYY")
                rh = c[2].time_input("Heure", value=maintenant.time().replace(second=0, microsecond=0), key="sma_r_h", step=60)
                apres = c[3].selectbox("État après remise", [gi.H24, gi.A_VIDE, gi.AVANT_18H, gi.APRES_18H], key="sma_r_e")
                c[4].write("")
                if c[4].form_submit_button("✅ Valider", type="primary"):
                    try:
                        gs.remettre_en_marche(ident, pd.Timestamp.combine(rj, rh), apres)
                        _ok("_sma_ok", f"Remise en marche enregistrée pour l'arrêt {ident} ; la centrale repasse « {apres} ».")
                    except ValueError as e:
                        _erreurs(e)
    reste = sites[sites["cle_site"].isin(sans_ep & perimetre)]
    if len(reste):
        with st.expander(f"⚠️ {len(reste)} centrale(s) à l'arrêt sans arrêt saisi — début inconnu (date à vérifier)"):
            st.caption("Ces centrales sont déclarées à l'arrêt (journal, état saisi ou bon d'intervention) mais aucun arrêt daté "
                       "n'a été déclaré : elles sont comptées indisponibles sur toute la période. Pour dater l'arrêt, déclare-le "
                       "ci-dessus ; si la centrale a redémarré, mets à jour son état dans « Parc de sites ».")
            st.dataframe(reste[["site", "phase", "region", "zone", "kwc", "cause", "etat_source", "etat_date"]].rename(columns={
                "site": "Site", "phase": "Phase", "region": "Région", "zone": "Zone", "kwc": "kWc", "cause": "Cause déclarée",
                "etat_source": "Source de l'état", "etat_date": "État constaté le"}), hide_index=True, width="stretch", height=300,
                column_config={"État constaté le": st.column_config.DateColumn(**DATE)})

    # ---- historique
    section_title("HISTORIQUE DES ARRÊTS DÉCLARÉS (12 DERNIERS MOIS)")
    h = ep[ep["debut"].isna() | (ep["debut"] >= maintenant - pd.DateOffset(months=12))].sort_values("debut", ascending=False, na_position="last")
    if h.empty:
        st.info("Aucun arrêt déclaré sur la plateforme. L'historique se constitue à partir des déclarations ci-dessus, des "
                "changements d'état saisis et de la case « Déclarer aussi un arrêt » des fiches.")
        return
    duree = ((h["fin"].fillna(maintenant) - h["debut"]).dt.total_seconds() / 86400).round(1)
    vue = pd.DataFrame({"N°": h["id"], "Site": h["site"], "Début": h["debut"], "Fin": h["fin"],
                        "État": h["fin"].map(lambda x: "en cours" if pd.isna(x) else "terminé"), "Durée (j)": duree,
                        "Date": h["date_a_verifier"].map({True: "⚠️ à vérifier", False: ""}), "Cause": h["cause"],
                        "Équipe": h["equipe"], "Source": h["source"], "Commentaire": h["commentaire"], "Déclaré par": h["auteur"]})
    st.dataframe(vue, hide_index=True, width="stretch", height=340,
                 column_config={"Début": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm"),
                                "Fin": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm"),
                                "Durée (j)": st.column_config.NumberColumn(format="%.1f j")})
    buf = io.BytesIO()
    vue.to_excel(buf, index=False)
    st.download_button("⬇️ Exporter l'historique (Excel)", buf.getvalue(), "arrets_declares.xlsx", key="sma_dl")


# ============================================================================= VISITES
def onglet_visites(sites: pd.DataFrame, visites: pd.DataFrame, f: pd.DataFrame, auj: pd.Timestamp) -> None:
    _flash("_smv_ok")
    infos = sites.drop_duplicates("cle_site").set_index("cle_site")
    perimetre_tot = set(sites.loc[sites["etat"].map(gi.GROUPE).isin(["En service H24", "Service partiel", "À l'arrêt"]), "cle_site"])
    eq = gs.equipes()
    chefs_connus = sorted({str(x) for x in list(visites["chef"].dropna()) + list(eq["chef"].dropna())}, key=str.lower)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Enregistrer une visite de site**")
        if not peut_modifier():
            st.info("🔒 Votre profil ne permet pas d'enregistrer une visite.")
        else:
            v = st.session_state.get("_smv_n", 0)
            s = sites.sort_values("site")
            lib = dict(zip(s["cle_site"], s["site"] + " (" + s["phase"].astype(str) + ", " + s["region"].astype(str) + ")"))
            with st.form(f"smv_new_{v}"):
                c = st.columns(2)
                k = c[0].selectbox("Site *", list(lib), format_func=lib.get, index=None, key=f"smv_site_{v}", placeholder="Nom de la centrale…")
                jour = c[1].date_input("Date de la visite *", value=auj.date(), max_value=auj.date(), key=f"smv_j_{v}", format="DD/MM/YYYY")
                c = st.columns(2)
                chef = c[0].selectbox("Chef d'équipe *", chefs_connus, index=None, accept_new_options=True, key=f"smv_chef_{v}",
                                      placeholder="Choisir ou saisir…")
                membres = c[1].text_input("Membres de l'équipe (séparés par des virgules)", key=f"smv_m_{v}")
                c = st.columns(3)
                typ = c[0].selectbox("Type", gi.TYPES_VISITE, key=f"smv_t_{v}")
                etat = c[1].selectbox("État constaté", gi.ETATS_SAISIE[:-1], index=None, key=f"smv_e_{v}", placeholder="Non relevé")
                equipe = c[2].selectbox("Équipe déclarée", list(eq.loc[eq["statut"] == "Active", "nom"]), index=None, key=f"smv_eq_{v}",
                                        placeholder="Facultatif")
                obs = st.text_area("Observations", key=f"smv_o_{v}", height=70)
                appliquer = st.checkbox("Mettre à jour l'état de la centrale avec l'état constaté", value=True, key=f"smv_a_{v}",
                                        help="Si l'état constaté diffère de l'état connu, il devient l'état de la centrale "
                                             "(un arrêt est alors ouvert ou clos en conséquence).")
                if st.form_submit_button("💾 Enregistrer la visite", type="primary"):
                    try:
                        ident = gs.enregistrer_visite({"site": None if k is None else infos.at[k, "site"], "date": pd.Timestamp(jour),
                                                       "chef": chef, "membres": membres, "equipe": equipe, "type": typ,
                                                       "etat_constate": etat, "observations": obs}, auj,
                                                      None if k is None else infos.at[k, "etat"], appliquer)
                        st.session_state["_smv_n"] = v + 1
                        _ok("_smv_ok", f"Visite {ident} enregistrée pour {infos.at[k, 'site']}.")
                    except ValueError as e:
                        _erreurs(e)
    with c2:
        st.markdown("**Couverture des visites**")
        c = st.columns(3)
        annees = sorted({int(a) for a in visites["date"].dt.year.unique()}, reverse=True) if len(visites) else []
        an = c[0].selectbox("Année", [None] + annees, format_func=lambda a: "Toutes" if a is None else str(a), key="smv_an")
        mo = c[1].selectbox("Mois", [None] + list(range(1, 13)), format_func=lambda m: "Tous" if m is None else gi.MOIS_COURTS[m - 1], key="smv_mo")
        reg = c[2].selectbox("Région", [None] + sorted(sites["region"].dropna().unique()), format_func=lambda r: "Toutes" if r is None else r, key="smv_reg")
        cles = set(sites["cle_site"]) if reg is None else set(sites.loc[sites["region"] == reg, "cle_site"])
        vf = gi.filtrer_visites(visites, an, mo, cles)
        k_ = gi.couverture_visites(vf, perimetre_tot & cles)
        sans_date = gs.interventions_sans_date(f)
        kpi_row([("Visites", n(k_["visites"]), "un passage par site et par jour"),
                 ("Centrales visitées", n(k_["centrales"]), None),
                 ("Couverture du parc", n(k_["couverture"], 0, " %"), f"sur {len(perimetre_tot & cles)} en exploitation"),
                 ("Jamais visitées (période)", n(k_["jamais"]), None)])
        kpi_row([("Interventions sans date", n(sans_date), "hors des filtres de période"),
                 ("Chefs d'équipe actifs", n(k_["chefs"]), f"{k_['sans_chef']} visite(s) sans chef"),
                 ("Préventives / correctives / urgences", f"{k_['preventives']} / {k_['correctives']} / {k_['urgences']}", None)])
        st.caption("Une visite = un passage d'équipe : visite saisie, inspection importée, bon d'intervention terminé ou "
                   "constat de défaut (l'équipe était sur place). Les inspections sont comptées avec les préventives ; un "
                   "constat de défaut URGENT est compté en urgence, les autres en correctives.")
    if visites.empty:
        st.info("Aucune visite connue.")
        return
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Visites par chef d'équipe**")
        st.dataframe(gi.visites_par_chef(vf), hide_index=True, width="stretch", height=330,
                     column_config={"Dernière visite": st.column_config.DateColumn(**DATE)})
    with c2:
        pm = gi.visites_par_mois(vf)
        if len(pm):
            fig = px.bar(pm, x="Mois", y=["Visites", "Sites distincts"], barmode="group", title="Visites par mois",
                         color_discrete_map={"Visites": "#0F766E", "Sites distincts": "#2563EB"}, labels={"value": "", "variable": ""})
            fig = plotly_base_layout(fig, height=330)
            fig.update_layout(legend=dict(orientation="h", y=-0.25), margin=dict(t=40))
            st.plotly_chart(fig, width="stretch")

    # ---- harmonisation des noms de chefs (rien n'est fusionné sans validation)
    corr = gs.correspondances_noms()
    groupes = gi.variantes_de_noms(visites["chef"].dropna().tolist() + eq["chef"].dropna().tolist(), corr)
    with st.expander(f"🧹 Noms de chefs d'équipe à harmoniser — {len(groupes)} proposition(s), {len(set(corr.values()))} nom(s) validé(s)"):
        st.caption("Propositions : noms identiques à la casse, aux accents et aux espaces près. Rien n'est fusionné tant que tu "
                   "n'as pas validé. Deux orthographes différentes d'une même personne se réunissent avec le formulaire du bas.")
        edition = peut_modifier()
        for i, grp in enumerate(groupes[:20]):
            c = st.columns([3, 2, 1])
            c[0].write(" · ".join(grp))
            retenu = c[1].selectbox("Nom retenu", grp, key=f"smv_var_{i}", label_visibility="collapsed")
            if edition and c[2].button("Valider", key=f"smv_var_ok_{i}"):
                gs.valider_correspondance(grp, retenu)
                _ok("_smv_ok", f"Correspondance validée : {', '.join(grp)} → {retenu}.")
        if edition:
            with st.form("smv_corr"):
                c = st.columns([3, 2, 1])
                autres = c[0].multiselect("Écritures désignant la même personne", chefs_connus, key="smv_corr_v")
                nom = c[1].text_input("Nom à retenir", key="smv_corr_n")
                c[2].write("")
                if c[2].form_submit_button("Réunir"):
                    try:
                        if len(autres) < 1:
                            raise ValueError("Choisis au moins une écriture.")
                        gs.valider_correspondance(autres, nom)
                        _ok("_smv_ok", f"Correspondance validée : {', '.join(autres)} → {' '.join(nom.split())}.")
                    except ValueError as e:
                        _erreurs(e)
        if corr:
            st.dataframe(pd.DataFrame({"Écriture (normalisée)": list(corr), "Nom retenu": list(corr.values())}), hide_index=True, width="stretch")

    section_title("JOURNAL DES VISITES")
    j = vf.sort_values("date", ascending=False)
    vue = pd.DataFrame({"Date": j["date"], "Site": j["site"], "Région": j["cle_site"].map(infos["region"]), "Chef d'équipe": j["chef"],
                        "Membres": j["membres"], "Équipe": j["equipe"], "Type": j["type"], "État constaté": j["etat_constate"],
                        "Observations": j["observations"], "Source": j["source"]})
    st.caption(f"{len(vue)} visite(s) pour la sélection.")
    st.dataframe(vue.head(500), hide_index=True, width="stretch", height=380,
                 column_config={"Date": st.column_config.DateColumn(**DATE), "Observations": st.column_config.TextColumn(width="large")})
    buf = io.BytesIO()
    vue.to_excel(buf, index=False)
    st.download_button("⬇️ Exporter le journal (Excel)", buf.getvalue(), "journal_des_visites.xlsx", key="smv_dl")


# ============================================================================= ÉQUIPES (module Ressources du GMAO)
def onglet_equipes(sites: pd.DataFrame, visites: pd.DataFrame, ref: pd.DataFrame, auj: pd.Timestamp) -> None:
    _flash("_sme_ok")
    edition = peut_modifier()
    eq = gs.equipes()
    bi = gc.table("gmao_bi")
    missions = gi.missions_depuis_bi(bi, set(eq["nom"]), gc.STATUTS_BI_OUVERTS, auj)
    zones_parc = {str(z) for z in sites["zone"].dropna()}
    k = gi.indicateurs_equipes(eq, missions, zones_parc, auj)
    kpi_row([("Équipes actives", n(k["actives"]), f"{k['inactives']} inactive(s)"),
             ("Personnes", n(k["personnes"]), "chefs + membres"),
             ("Zones couvertes", f"{k['zones_couvertes']} / {k['zones']}", None),
             ("Missions à venir", n(k["a_venir"]), None),
             ("Missions en retard", n(k["en_retard"]), "date dépassée, non réalisées"),
             ("Taux de réalisation 30 j", n(k["realisation_taux"], 0, " %"), f"{k['realisation_echues']} mission(s) échue(s)")])

    c1, c2 = st.columns(2)
    with c1:
        if not edition:
            st.info("🔒 Votre profil ne permet pas de créer ou de modifier une équipe.")
        else:
            pre = st.session_state.get("_sme_pre", {})
            choix = st.selectbox("Équipe", [None] + list(eq["nom"]), format_func=lambda x: "➕ Nouvelle équipe" if x is None else f"✏️ Modifier : {x}",
                                 key=f"sme_choix_{st.session_state.get('_sme_n', 0)}")
            a = eq[eq["nom"] == choix].iloc[0] if choix else None
            val = lambda champ, defaut="": (a[champ] if a is not None and not gi.est_vide(a[champ]) else pre.get(champ, defaut))  # noqa: E731
            v = st.session_state.get("_sme_n", 0)
            cle_f = f"{v}_{choix}_{pre.get('chef', '')}"
            zones = sorted(zones_parc | {str(z) for z in eq["zone"].dropna()})
            with st.form(f"sme_form_{cle_f}"):
                st.markdown("**Créer une équipe**" if a is None else f"**Modifier l'équipe « {choix} »**")
                c = st.columns(2)
                nom = c[0].text_input("Nom de l'équipe *", value=val("nom"), key=f"sme_nom_{cle_f}", placeholder="ex. Équipe Nord 1")
                zone = c[1].selectbox("Zone *", zones, index=zones.index(val("zone")) if val("zone") in zones else None,
                                      accept_new_options=True, key=f"sme_zone_{cle_f}", placeholder="Choisir ou saisir…")
                c = st.columns(2)
                chef = c[0].text_input("Chef d'équipe *", value=val("chef"), key=f"sme_chef_{cle_f}")
                tel = c[1].text_input("Téléphone du chef", value=val("telephone"), key=f"sme_tel_{cle_f}")
                statut = st.selectbox("Statut", gi.STATUTS_EQUIPE, index=gi.STATUTS_EQUIPE.index(val("statut", "Active")), key=f"sme_st_{cle_f}")
                membres = st.text_input("Membres (séparés par des virgules)", value=val("membres"), key=f"sme_m_{cle_f}", placeholder="Nom 1, Nom 2, …")
                if st.form_submit_button("💾 Enregistrer l'équipe", type="primary"):
                    try:
                        gs.enregistrer_equipe({"nom": nom, "zone": zone, "chef": chef, "telephone": tel, "statut": statut, "membres": membres}, choix)
                        st.session_state.pop("_sme_pre", None)
                        st.session_state["_sme_n"] = v + 1
                        _ok("_sme_ok", f"Équipe « {' '.join(nom.split())} » enregistrée.")
                    except ValueError as e:
                        _erreurs(e)
    with c2:
        actives = list(eq.loc[eq["statut"] == "Active", "nom"])
        if not edition:
            st.info("🔒 Votre profil ne permet pas de programmer une mission.")
        elif not actives:
            st.info("Programmer une mission : crée d'abord une équipe active.")
        else:
            info = ref.assign(_k=ref["Nom du site"].map(g.cle)).drop_duplicates("_k").set_index("_k")
            s = sites[sites["cle_site"].isin(info.index)].sort_values("site")
            lib = dict(zip(s["cle_site"], s["site"] + " (" + s["phase"].astype(str) + ", " + s["region"].astype(str) + ")"))
            w = st.session_state.get("_smm_n", 0)
            with st.form(f"smm_form_{w}"):
                st.markdown("**Programmer une mission**")
                c = st.columns(2)
                ks = c[0].selectbox("Site *", list(lib), format_func=lib.get, index=None, key=f"smm_site_{w}", placeholder="Nom de la centrale…")
                quand = c[1].date_input("Date prévue *", value=auj.date(), min_value=auj.date(), key=f"smm_d_{w}", format="DD/MM/YYYY")
                c = st.columns(2)
                equipe = c[0].selectbox("Équipe *", actives, key=f"smm_eq_{w}",
                                        format_func=lambda x: f"{x} ({eq.set_index('nom').at[x, 'zone']})")
                typ = c[1].selectbox("Type", list(gi.TYPES_MISSION), key=f"smm_t_{w}")
                consignes = st.text_input("Objet / consignes", key=f"smm_c_{w}")
                if st.form_submit_button("🗓️ Programmer", type="primary"):
                    try:
                        r = None if ks is None else s.set_index("cle_site").loc[ks]
                        ident = gs.programmer_mission(None if r is None else {"site": r["site"], "site_id": info.at[ks, "site_id"],
                                                                              "phase": r["phase"], "region": r["region"]},
                                                      pd.Timestamp(quand), equipe, typ, consignes, auj)
                        st.session_state["_smm_n"] = w + 1
                        _ok("_sme_ok", f"Mission {ident} programmée pour {r['site']} le {pd.Timestamp(quand):%d/%m/%Y} ({equipe}).")
                    except ValueError as e:
                        _erreurs(e)
            st.caption("Une mission est un bon d'intervention planifié : elle apparaît dans « Bons d'intervention » et dans "
                       "« Préventif & planning », où elle se traite et se clôture.")

    section_title("ÉQUIPES DE MAINTENANCE")
    if eq.empty:
        st.info("Aucune équipe déclarée. Crée-les ci-dessus, ou à partir des chefs de l'historique en bas de page.")
    else:
        fiches_eq = bi[bi["type"] == "Corrective"].groupby("equipe").size().to_dict() if len(bi) else {}
        t = gi.tableau_equipes(eq, visites, missions, sites, fiches_eq, auj)
        t["Membres (noms)"] = eq["membres"].values
        st.dataframe(t, hide_index=True, width="stretch",
                     column_config={"Dernière activité": st.column_config.DateColumn(**DATE),
                                    "Membres (noms)": st.column_config.TextColumn(width="large")})
        st.caption("Interventions et sites visités : visites portant le nom de l'équipe, ou dont le chef est celui de "
                   "l'équipe. Sites affectés : centrales dont le responsable de zone (journal des affectations) est le chef.")

        section_title("PLANNING DES MISSIONS")
        c = st.columns([1.5, 1.5, 4])
        f_eq = c[0].selectbox("Équipe", [None] + list(eq["nom"]), format_func=lambda x: "Toutes" if x is None else x, key="smm_f_eq")
        f_st = c[1].selectbox("Missions", ["À traiter", "Réalisées", "Toutes"], key="smm_f_st")
        m = missions if f_eq is None else missions[missions["equipe"] == f_eq]
        m = m[m["statut"].isin(["À venir", "En retard"])] if f_st == "À traiter" else m[m["statut"] == "Réalisée"] if f_st == "Réalisées" else m
        if m.empty:
            st.info("Aucune mission.")
        else:
            zone = dict(zip(sites["site"], sites["zone"]))
            st.dataframe(pd.DataFrame({"Date prévue": m["date_prevue"], "Site": m["site"], "Zone": m["site"].map(zone), "Équipe": m["equipe"],
                                       "Type": m["type"], "Objet": m["description"], "Statut": m["statut"], "Bon d'intervention": m["id"]})
                         .sort_values("Date prévue"), hide_index=True, width="stretch",
                         column_config={"Date prévue": st.column_config.DateColumn(**DATE)})

    c1, c2 = st.columns(2)
    with c1:
        if len(eq):
            act = t[["Équipe", "Interventions 12 mois", "Sites visités"]].rename(columns={"Interventions 12 mois": "Visites", "Sites visités": "Sites distincts"})
            fig = px.bar(act, x="Équipe", y=["Visites", "Sites distincts"], barmode="group", title="Activité par équipe (12 derniers mois)",
                         color_discrete_map={"Visites": "#0F766E", "Sites distincts": "#2563EB"}, labels={"value": "", "variable": ""})
            fig = plotly_base_layout(fig, height=320)
            fig.update_layout(legend=dict(orientation="h", y=-0.3), margin=dict(t=40))
            st.plotly_chart(fig, width="stretch")
    with c2:
        st.markdown("**Chefs d'équipe de l'historique sans équipe déclarée**")
        orph = gi.chefs_sans_equipe(visites, eq, dict(zip(sites["cle_site"], sites["zone"])))
        if orph.empty:
            st.success("Tous les chefs de l'historique des visites appartiennent à une équipe déclarée.")
        for i, r in enumerate(orph.head(15).itertuples()):
            c = st.columns([3, 1, 1.2, 1.4, 1.6])
            c[0].write(r.Chef)
            c[1].write(f"{r.Visites} visite(s)")
            c[2].write(r._3 or "—")
            c[3].write("—" if pd.isna(r.Dernière) else f"{r.Dernière:%d/%m/%Y}")
            if edition and c[4].button("➕ Équipe", key=f"sme_orph_{i}", help="Créer l'équipe de ce chef"):
                st.session_state["_sme_pre"] = {"chef": r.Chef, "zone": r._3 or ""}
                st.session_state["_sme_n"] = st.session_state.get("_sme_n", 0) + 1     # repart sur « Nouvelle équipe »
                st.rerun()
        if len(orph) > 15:
            st.caption(f"… et {len(orph) - 15} autre(s).")
        if len(orph):
            st.caption("« ➕ Équipe » préremplit le formulaire du haut avec le chef et sa zone principale ; il reste à "
                       "donner un nom à l'équipe et à enregistrer.")
