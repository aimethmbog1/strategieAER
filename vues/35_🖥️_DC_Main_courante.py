import io
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from dc import depot, exploitation as ex, modele, notifications
from dc.ui import (COULEURS, ICONES, ROLES_GESTION, ROLES_INSPECTION, bandeau, colorer_severite, exiger_lecture, initialiser,
                   peut, style)
from utils.ui import PAGE_ICON, inject_base_style, kpi_row, render_sidebar_footer, section_title

st.set_page_config(page_title="Data Center — main courante — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()
exiger_lecture()
initialiser()
style()
bandeau("Main courante, passation de consignes et annuaire",
        "Journal d'événements partagé entre les équipes · relève de poste · intervenants et fournisseurs")

for cle, fn in (("_dcmc_ok", st.success), ("_dcmc_warn", st.warning)):
    if st.session_state.get(cle):
        fn(st.session_state.pop(cle))


def ok(msg: str, avert: str | None = None):
    st.session_state["_dcmc_ok"] = msg
    if avert:
        st.session_state["_dcmc_warn"] = avert
    st.rerun()


auj = depot.maintenant()
ecrire = peut(ROLES_INSPECTION)
gestion = peut(ROLES_GESTION)
_, nom_u = ex.identite()
eq = depot.equipements()
codes = dict(zip(eq["id"], eq["code"]))
ev = ex.evenements()
if len(ev):
    ev["horodatage"] = pd.to_datetime(ev["horodatage"])
pa = ex.passations()
en_attente = pa[pa["acceptee"].isna()] if len(pa) else pa
ct = ex.contacts()

kpi_row([
    ("Entrées sur 24 h", str(int((ev["horodatage"] >= auj - timedelta(hours=24)).sum()) if len(ev) else 0), None),
    ("Entrées sur 7 jours", str(int((ev["horodatage"] >= auj - timedelta(days=7)).sum()) if len(ev) else 0), None),
    ("Passations en attente", str(len(en_attente)), None),
    ("Dernière passation", f"{pa['horodatage'].iloc[0]:%d/%m à %H:%M}" if len(pa) else "—",
     pa["sortant"].iloc[0] if len(pa) else None),
    ("Contacts de l'annuaire", str(len(ct)), f"{int((ct['niveau'] > 0).sum()) if len(ct) else 0} destinataire(s) d'alertes"),
])

t_mc, t_pa, t_an = st.tabs(["📒 Main courante", f"🔄 Passation de consignes ({len(en_attente)} à prendre)", "📇 Annuaire"])

# ============================================================================= MAIN COURANTE
with t_mc:
    if ecrire:
        with st.expander("➕ Ajouter une entrée", expanded=ev.empty):
            n = st.session_state.get("_dcmc_n", 0)
            with st.form(f"dcmc_new_{n}"):
                c1, c2, c3, c4 = st.columns(4)
                cat = c1.selectbox("Catégorie", [c for c in modele.CATEGORIES_EVENEMENT if c not in ("Alerte", "Passation", "Rectificatif")],
                                   key=f"dcmc_cat_{n}")
                sev = c2.selectbox("Sévérité", modele.SEVERITES_ALERTE, key=f"dcmc_sev_{n}")
                systeme = c3.selectbox("Système", [None] + modele.SYSTEMES, key=f"dcmc_sys_{n}",
                                       format_func=lambda s: "—" if s is None else s)
                code = c4.selectbox("Équipement", [None] + sorted(eq["code"]), key=f"dcmc_eq_{n}",
                                    format_func=lambda c: "—" if c is None else c)
                c5, c6, c7 = st.columns([1, 1, 2])
                jour = c5.date_input("Date du fait", value=auj.date(), max_value=auj.date(), key=f"dcmc_j_{n}", format="DD/MM/YYYY")
                heure = c6.time_input("Heure (Douala)", value=auj.time().replace(second=0), key=f"dcmc_h_{n}", step=60)
                niveaux = c7.multiselect("Diffuser aussi par message aux contacts de niveau", list(modele.NIVEAUX),
                                         key=f"dcmc_niv_{n}", format_func=lambda i: modele.NIVEAUX[i],
                                         help="Notification ciblée : laisse vide pour une simple consignation.")
                desc = st.text_area("Description", key=f"dcmc_desc_{n}", height=100,
                                    placeholder="Qui, quoi, où, constat, action réalisée, suite à donner.")
                envoi = st.form_submit_button("💾 Consigner", type="primary")
            if envoi:
                try:
                    eid = ex.ajouter_evenement(cat, desc, sev, systeme,
                                               None if code is None else int(eq.set_index("code").at[code, "id"]),
                                               quand=datetime.combine(jour, heure))
                    avert = None
                    msg = f"Entrée n° {eid} consignée."
                    if niveaux:
                        r = ex.diffuser_evenement(eid, niveaux)
                        msg += f" Diffusion : {r['envoyées']} message(s) envoyé(s) à {r['destinataires']} contact(s)."
                        if r["destinataires"] == 0 or r["envoyées"] < len(r["statuts"]):
                            avert = ("Diffusion incomplète : " + ("aucun contact actif à ces niveaux." if r["destinataires"] == 0
                                     else "certains messages ne sont pas partis (voir Alertes → Notifications et escalade)."))
                    st.session_state["_dcmc_n"] = n + 1
                    ok(msg, avert)
                except ValueError as e:
                    st.error(str(e))
        if len(ev):
            with st.expander("✏️ Rectifier une entrée"):
                st.caption("La main courante ne se modifie pas et ne s'efface pas : une erreur se corrige par un "
                           "rectificatif, qui reste lié à l'entrée d'origine.")
                with st.form("dcmc_rect"):
                    cible = st.selectbox("Entrée à rectifier", list(ev["id"]), key="dcmc_rect_id",
                                         format_func=lambda i: f"n° {i} — {ev.set_index('id').at[i, 'horodatage']:%d/%m %H:%M} — "
                                                               f"{str(ev.set_index('id').at[i, 'description'])[:80]}")
                    txt = st.text_area("Rectification", key="dcmc_rect_txt", height=70)
                    if st.form_submit_button("💾 Enregistrer le rectificatif"):
                        try:
                            rid = ex.ajouter_evenement("Rectificatif", f"Rectificatif de l'entrée n° {cible} : {txt}"
                                                       if txt.strip() else "", rectifie_id=int(cible))
                            ok(f"Rectificatif n° {rid} enregistré.")
                        except ValueError as e:
                            st.error(str(e))
    else:
        st.info("🔒 Votre profil permet de lire la main courante, pas d'y écrire.")

    section_title("JOURNAL")
    if ev.empty:
        st.info("La main courante est vide.")
    else:
        c1, c2, c3, c4, c5 = st.columns([1, 1.4, 1.2, 1.4, 1.4])
        d0 = c1.date_input("Depuis", value=(auj - timedelta(days=7)).date(), key="dcmc_f_d0", format="DD/MM/YYYY")
        fc = c2.multiselect("Catégorie", modele.CATEGORIES_EVENEMENT, key="dcmc_f_c")
        fs = c3.multiselect("Sévérité", modele.SEVERITES_ALERTE, key="dcmc_f_s")
        fq = c4.text_input("Recherche", key="dcmc_f_q")
        auto = c5.toggle("Afficher les entrées automatiques", value=True, key="dcmc_f_a",
                         help="Alertes émises, acquittées, résolues et escalades, consignées par le module.")
        v = ev[ev["horodatage"] >= pd.Timestamp(d0)]
        if fc:
            v = v[v["categorie"].isin(fc)]
        if fs:
            v = v[v["severite"].isin(fs)]
        if fq:
            v = v[v["description"].str.contains(fq, case=False, regex=False, na=False)]
        if not auto:
            v = v[~v["automatique"].astype(bool)]
        rectifiees = set(ev["rectifie_id"].dropna().astype(int))
        vue = v.assign(Équipement=v["equipement_id"].map(codes),
                       Rectifiée=v["id"].map(lambda i: "Oui" if i in rectifiees else ""),
                       Auteur=v["auteur_nom"].fillna(v["auteur"]))[
            ["id", "horodatage", "categorie", "severite", "description", "systeme", "Équipement", "Auteur", "Rectifiée"]].rename(
            columns={"id": "N°", "horodatage": "Date", "categorie": "Catégorie", "severite": "Sévérité",
                     "description": "Description", "systeme": "Système"})
        st.caption(f"{len(vue)} entrée(s), de la plus récente à la plus ancienne.")
        st.dataframe(vue.style.map(colorer_severite, subset=["Sévérité"]), hide_index=True, width="stretch", height=460,
                     column_config={"Date": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm"),
                                    "Description": st.column_config.TextColumn(width="large")})
        buf = io.BytesIO()
        vue.to_excel(buf, index=False)
        st.download_button("⬇️ Exporter (Excel)", buf.getvalue(), "main_courante_data_center.xlsx", key="dcmc_dl")

# ============================================================================= PASSATION
with t_pa:
    def afficher(p) -> None:
        sev = p["etat_general"] or "OK"
        st.markdown(f"**Passation n° {p['id']}** — {p['horodatage']:%d/%m/%Y à %H:%M} · poste : {p['poste'] or '—'} · "
                    f"de **{p['sortant']}** à **{p['entrant'] or '—'}** · état général : {ICONES.get(sev, '')} **{sev}**")
        c1, c2, c3 = st.columns(3)
        c1.markdown("**Faits marquants**\n\n" + (p["faits_marquants"] or "—"))
        c2.markdown("**Travaux en cours**\n\n" + (p["travaux_en_cours"] or "—"))
        c3.markdown("**Consignes**\n\n" + (p["consignes"] or "—"))
        with st.expander("Situation chiffrée au moment de la passation"):
            st.text(p["situation"] or "—")

    if len(en_attente):
        section_title("PASSATION À PRENDRE EN COMPTE")
        for _, p in en_attente.iterrows():
            with st.container(border=True):
                afficher(p)
                if ecrire:
                    with st.form(f"dcpa_acc_{p['id']}"):
                        c1, c2 = st.columns([1, 2])
                        par = c1.text_input("Je prends le poste — nom", value=nom_u, key=f"dcpa_par_{p['id']}")
                        resv = c2.text_input("Réserves éventuelles", key=f"dcpa_res_{p['id']}",
                                             placeholder="Laisse vide si les consignes sont claires et complètes")
                        if st.form_submit_button("✅ J'ai lu les consignes et je prends le poste", type="primary"):
                            try:
                                ex.accepter_passation(int(p["id"]), par, resv)
                                ok(f"Passation n° {p['id']} prise en compte par {par}.")
                            except ValueError as e:
                                st.error(str(e))
    elif len(pa):
        st.success("Toutes les passations ont été prises en compte.")

    section_title("NOUVELLE PASSATION")
    if not ecrire:
        st.info("🔒 Votre profil permet de lire les passations, pas d'en rédiger.")
    else:
        etat, situation = ex.situation_actuelle()
        st.markdown(f"État général calculé : {ICONES.get(etat, '')} **{etat}** — la situation ci-dessous est figée dans "
                    "la passation au moment de l'enregistrement.")
        st.text(situation)
        n = st.session_state.get("_dcpa_n", 0)
        internes = sorted(ct.loc[ct["type"] == "Interne AER", "nom"]) if len(ct) else []
        with st.form(f"dcpa_new_{n}"):
            c1, c2, c3 = st.columns(3)
            poste = c1.selectbox("Poste qui se termine", modele.POSTES, key=f"dcpa_poste_{n}")
            sortant = c2.text_input("Sortant", value=nom_u, key=f"dcpa_sortant_{n}")
            entrant = c3.selectbox("Entrant", internes, index=None, accept_new_options=True, key=f"dcpa_entrant_{n}",
                                   placeholder="Choisir ou saisir un nom") if internes else \
                c3.text_input("Entrant", key=f"dcpa_entrant_{n}")
            faits = st.text_area("Faits marquants du poste", key=f"dcpa_faits_{n}", height=80,
                                 placeholder="Incidents, alarmes, visites, coupures… ou « Néant ».")
            travaux = st.text_area("Travaux en cours ou programmés", key=f"dcpa_travaux_{n}", height=70)
            consignes = st.text_area("Consignes pour l'équipe entrante", key=f"dcpa_consignes_{n}", height=80,
                                     placeholder="Points à surveiller, actions à mener, personnes à prévenir.")
            if st.form_submit_button("💾 Enregistrer la passation", type="primary"):
                try:
                    pid = ex.enregistrer_passation(poste, sortant, entrant or "", faits, travaux, consignes)
                    st.session_state["_dcpa_n"] = n + 1
                    ok(f"Passation n° {pid} enregistrée. Elle attend la prise de poste de l'équipe entrante.")
                except ValueError as e:
                    st.error(str(e))

    if len(pa):
        section_title("HISTORIQUE DES PASSATIONS")
        h = pa.assign(Prise=pa["acceptee"].map(lambda x: "En attente" if pd.isna(x) else f"{x:%d/%m/%Y %H:%M}"))[
            ["id", "horodatage", "poste", "sortant", "entrant", "etat_general", "Prise", "acceptee_par", "reserves"]].rename(
            columns={"id": "N°", "horodatage": "Date", "poste": "Poste", "sortant": "Sortant", "entrant": "Entrant",
                     "etat_general": "État", "Prise": "Prise de poste", "acceptee_par": "Prise par", "reserves": "Réserves"})
        st.dataframe(h.style.map(colorer_severite, subset=["État"]), hide_index=True, width="stretch",
                     column_config={"Date": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm")})
        choix = st.selectbox("Relire une passation", list(pa["id"]), index=None, key="dcpa_voir",
                             format_func=lambda i: f"n° {i} — {pa.set_index('id').at[i, 'horodatage']:%d/%m/%Y %H:%M} — "
                                                   f"{pa.set_index('id').at[i, 'sortant']}")
        if choix is not None:
            with st.container(border=True):
                afficher(pa.set_index("id", drop=False).loc[choix])

# ============================================================================= ANNUAIRE
with t_an:
    if not ecrire:
        st.info("🔒 L'annuaire (coordonnées personnelles) est réservé aux équipes du Data Center.")
    else:
        canaux = notifications.canaux_configures()
        st.caption(
            "Intervenants internes, fournisseurs et prestataires. Le **niveau** désigne qui reçoit les alertes : "
            + " ; ".join(f"**{k}** = {v.split(' — ')[1]}" for k, v in modele.NIVEAUX.items())
            + " ; **0** = contact d'annuaire qui ne reçoit pas d'alerte. « Sévérité minimale » : seuil à partir duquel "
              "le contact est notifié. « Système » : limite les alertes reçues à un système.")
        if ct.empty:
            st.warning("L'annuaire est vide : aucune alerte ne peut être notifiée. **À compléter** — au minimum un "
                       "contact de niveau 1 et un de niveau 2, avec une adresse de courriel ou un identifiant Telegram.")
        cols = ["id"] + ex.COLONNES_CONTACT
        config = {
            "id": None,
            "nom": st.column_config.TextColumn("Nom", required=True, max_chars=120),
            "fonction": st.column_config.TextColumn("Fonction", max_chars=160),
            "organisation": st.column_config.TextColumn("Organisation", max_chars=160),
            "type": st.column_config.SelectboxColumn("Type", options=modele.TYPES_CONTACT, default="Interne AER"),
            "systeme": st.column_config.SelectboxColumn("Système", options=["Tous"] + modele.SYSTEMES, default="Tous"),
            "niveau": st.column_config.SelectboxColumn("Niveau", options=[0, 1, 2, 3], default=0),
            "severite_min": st.column_config.SelectboxColumn("Sévérité minimale", options=["Avertissement", "Critique"],
                                                             default="Avertissement"),
            "courriel": st.column_config.TextColumn("Courriel", max_chars=160),
            "telephone": st.column_config.TextColumn("Téléphone", max_chars=60),
            "telegram_id": st.column_config.TextColumn("Identifiant Telegram", max_chars=40,
                                                       help="Numéro de conversation (chat_id) obtenu après que la "
                                                            "personne a écrit au bot de l'AER."),
            "par_courriel": st.column_config.CheckboxColumn("Par courriel", default=True),
            "par_telegram": st.column_config.CheckboxColumn("Par Telegram", default=False),
            "actif": st.column_config.CheckboxColumn("Actif", default=True),
            "observations": st.column_config.TextColumn("Observations", width="medium"),
        }
        ed = st.data_editor(ct[cols] if len(ct) else pd.DataFrame(columns=cols), hide_index=True, width="stretch",
                            height=380, key="dcan_ed", num_rows="dynamic" if gestion else "fixed", disabled=not gestion,
                            column_config=config)
        if gestion:
            c1, c2 = st.columns([1, 3])
            if c1.button("💾 Enregistrer l'annuaire", type="primary", key="dcan_ok"):
                try:
                    b = ex.enregistrer_contacts(ct, ed)
                    ok(f"Annuaire enregistré : {b['créés']} créé(s), {b['modifiés']} modifié(s), {b['supprimés']} supprimé(s).")
                except ValueError as e:
                    st.error("Annuaire non enregistré :\n\n- " + "\n- ".join(str(e).split("\n")))
            if len(ct):
                buf = io.BytesIO()
                ct[ex.COLONNES_CONTACT].to_excel(buf, index=False)
                c2.download_button("⬇️ Exporter l'annuaire (Excel)", buf.getvalue(), "annuaire_data_center.xlsx", key="dcan_dl")

            section_title("VÉRIFIER LA RÉCEPTION")
            etats = " · ".join(f"{'🟢' if a else '⚪'} {c} {'configuré' if a else 'non configuré'}" for c, a in canaux.items())
            st.caption(f"Canaux d'envoi : {etats}. Envoie un message de test avant de compter sur une alerte réelle.")
            dest = ct[ct["actif"].astype(bool)] if len(ct) else ct
            if len(dest):
                c1, c2 = st.columns([2, 1])
                cid = c1.selectbox("Contact", list(dest["id"]), key="dcan_test_id", label_visibility="collapsed",
                                   format_func=lambda i: dest.set_index("id").at[i, "nom"])
                if c2.button("✉️ Envoyer un message de test", key="dcan_test"):
                    statuts = ex.message_test(int(cid))
                    (st.success if statuts and all(s == "Envoyée" for s in statuts) else st.warning)(
                        "Résultat : " + ", ".join(statuts) + ". Détail dans Alertes → Notifications et escalade.")
        else:
            st.caption("Lecture seule : l'annuaire est tenu par les profils Administrateur et Monitoring & statistiques.")

render_sidebar_footer("")
