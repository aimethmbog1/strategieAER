import html
import io
from datetime import timedelta

import pandas as pd
import streamlit as st

from dc import depot, exploitation as ex, modele, notifications
from dc.regles import format_duree, prochain_palier
from dc.ui import (COULEURS, ICONES, ROLES_INSPECTION, bandeau, colorer_severite, exiger_lecture, initialiser, peut, style)
from utils.ui import PAGE_ICON, inject_base_style, kpi_row, render_sidebar_footer, section_title

st.set_page_config(page_title="Data Center — alertes — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()
exiger_lecture()
initialiser()
style()
bandeau("Centre d'alertes du Data Center",
        "Alertes issues des inspections ou signalées par les équipes · acquittement, escalade et résolution")
st.markdown("""<style>
.dc-al{border-left:6px solid #9CA3AF;background:#F8FAFC;border-radius:8px;padding:.55rem .8rem;margin-bottom:.45rem}
.dc-al b{font-size:.98rem;color:#0F172A}.dc-al small{display:block;color:#475569;font-size:.8rem;margin-top:.15rem}
</style>""", unsafe_allow_html=True)

# Mise à jour à l'ouverture : écarts d'inspection → alertes, puis paliers d'escalade échus
try:
    sync = ex.synchroniser_alertes()
    escalades = ex.traiter_escalades()
except Exception as e:  # noqa: BLE001 — la page doit rester consultable même si une notification échoue
    sync, escalades = {}, []
    st.error(f"La mise à jour automatique des alertes a échoué : {type(e).__name__} — {e}")

for cle, fn in (("_dcal_ok", st.success), ("_dcal_err", st.error)):
    if st.session_state.get(cle):
        fn(st.session_state.pop(cle))
if escalades:
    st.warning("📣 " + " · ".join(f"alerte n° {x['alerte']} → niveau {x['niveau']} ({x['envoyées']} message(s) envoyé(s))"
                                   for x in escalades))

auj = depot.maintenant()
agir = peut(ROLES_INSPECTION)
_, nom_u = ex.identite()
eq = depot.equipements()
codes = dict(zip(eq["id"], eq["code"]))
al = ex.alertes()
enc = ex.alertes_en_cours(al)
ind = ex.indicateurs_alertes(al, auj - timedelta(days=30))
pal = ex.paliers()
ct = ex.contacts(True)
canaux = notifications.canaux_configures()

kpi_row([
    ("Non acquittées", str(ind["non_acquittees"]), None),
    ("Critiques en cours", str(ind["critiques"]), None),
    ("Alertes en cours", str(ind["en_cours"]), f"{ind['emises']} émise(s) en 30 jours"),
    ("Délai moyen d'acquittement", format_duree(ind["delai_acquittement"]), "30 derniers jours"),
    ("Délai moyen de résolution", format_duree(ind["delai_resolution"]), "30 derniers jours"),
])

# Défauts de configuration qui empêcheraient une alerte d'atteindre quelqu'un
manques = []
if ct.empty or not (ct["niveau"] == 1).any():
    manques.append("aucun contact actif de niveau 1 dans l'annuaire")
if not any(canaux.values()):
    manques.append("aucun canal d'envoi configuré (courriel ou Telegram)")
if manques:
    st.warning("⚠️ Les alertes restent visibles ici mais ne sont notifiées à personne : " + " ; ".join(manques)
               + ". À compléter dans « Main courante et passation → Annuaire » et dans les secrets de l'application.")


def ok(msg: str):
    st.session_state["_dcal_ok"] = msg
    st.rerun()


def libelle(a) -> str:
    return f"n° {a.id} · {a.severite} · {a.titre[:90]}"


t_enc, t_new, t_hist, t_not = st.tabs([f"🚨 En cours ({len(enc)})", "➕ Signaler une alerte", "📚 Historique",
                                       "✉️ Notifications et escalade"])

# ============================================================================= EN COURS
with t_enc:
    if enc.empty:
        st.success("Aucune alerte en cours.")
    else:
        for a in enc.head(40).itertuples():
            depuis = (auj - a.emise.to_pydatetime()).total_seconds() / 60
            if a.statut == "Acquittée":
                suite = f"Acquittée par {a.acquittee_par} le {a.acquittee:%d/%m à %H:%M}" + (
                    f" — {a.commentaire_acquittement}" if isinstance(a.commentaire_acquittement, str) else "")
            else:
                pp = prochain_palier(a.severite, a.emise.to_pydatetime(), int(a.niveau_notifie or 0), pal)
                niv = f"niveau {int(a.niveau_notifie)} notifié" if a.niveau_notifie else "aucun niveau notifié"
                suite = f"NON ACQUITTÉE — {niv}" + (
                    f" ; escalade au niveau {pp[0].niveau} à {pp[1]:%H:%M le %d/%m}" if pp else " ; dernier niveau atteint")
            st.markdown(
                f"<div class='dc-al' style='border-left-color:{COULEURS.get(a.severite, '#9CA3AF')}'>"
                f"<b>{ICONES.get(a.severite, '')} n° {a.id} — {html.escape(a.titre)}</b>"
                f"<small>{a.severite} · {html.escape(str(codes.get(a.equipement_id, '—')))} · {html.escape(a.systeme or '—')} · "
                f"{a.origine} · émise le {a.emise:%d/%m/%Y à %H:%M} (il y a {format_duree(depuis)})</small>"
                f"<small>{html.escape(suite)}</small></div>", unsafe_allow_html=True)
        if len(enc) > 40:
            st.caption(f"{len(enc) - 40} autre(s) alerte(s) en cours : voir l'onglet Historique.")

        section_title("TRAITER UNE ALERTE")
        if not agir:
            st.info("🔒 Votre profil permet de consulter les alertes, pas de les traiter.")
        else:
            choix = st.selectbox("Alerte", list(enc["id"]), key="dcal_sel",
                                 format_func=lambda i: libelle(enc.set_index("id", drop=False).loc[i]))
            a = enc.set_index("id", drop=False).loc[choix]
            if isinstance(a["description"], str):
                st.caption(a["description"])
            c1, c2 = st.columns(2)
            with c1, st.form(f"dcal_acq_{choix}"):
                st.markdown("**Acquitter** — « j'ai vu l'alerte et je la prends en charge ». L'escalade s'arrête.")
                par = st.text_input("Nom", value=nom_u, key=f"dcal_acq_par_{choix}")
                com = st.text_input("Commentaire (facultatif)", key=f"dcal_acq_com_{choix}",
                                    placeholder="Ex. : en route vers la salle")
                if st.form_submit_button("✅ Acquitter", type="primary", disabled=a["statut"] != "Ouverte"):
                    try:
                        ex.acquitter(int(choix), par, com)
                        ok(f"Alerte n° {choix} acquittée par {par}.")
                    except ValueError as e:
                        st.error(str(e))
                if a["statut"] != "Ouverte":
                    st.caption("Déjà acquittée.")
            with c2, st.form(f"dcal_res_{choix}"):
                st.markdown("**Résoudre** — le défaut est corrigé. La description servira à l'analyse des pannes.")
                par_r = st.text_input("Nom", value=nom_u, key=f"dcal_res_par_{choix}")
                res = st.text_area("Cause constatée et action réalisée", key=f"dcal_res_txt_{choix}", height=80)
                if st.form_submit_button("🏁 Résoudre l'alerte"):
                    try:
                        ex.resoudre(int(choix), par_r, res)
                        ok(f"Alerte n° {choix} résolue.")
                    except ValueError as e:
                        st.error(str(e))
            if a["origine"] == "Inspection":
                st.caption("Cette alerte vient d'un contrôle d'inspection : elle se résout aussi d'elle-même dès qu'une "
                           "inspection suivante relève le contrôle conforme.")

# ============================================================================= SIGNALER
with t_new:
    if not agir:
        st.info("🔒 Votre profil ne permet pas de signaler une alerte.")
    else:
        st.caption("Pour un défaut constaté hors inspection : alarme de l'ECC800, coupure secteur, fuite, panne réseau, "
                   "intrusion… Une alerte critique ou d'avertissement est notifiée au niveau 1 puis escaladée ; une "
                   "information est seulement affichée.")
        n = st.session_state.get("_dcal_n", 0)
        with st.form(f"dcal_new_{n}"):
            c1, c2 = st.columns([1, 2])
            sev = c1.radio("Sévérité", modele.SEVERITES_ALERTE[::-1], key=f"dcal_sev_{n}")
            titre = c2.text_input("Objet de l'alerte", key=f"dcal_titre_{n}", max_chars=200,
                                  placeholder="Ex. : coupure secteur, onduleur sur batteries")
            c3, c4 = c2.columns(2)
            code = c3.selectbox("Équipement concerné (facultatif)", [None] + sorted(eq["code"]), key=f"dcal_eq_{n}",
                                format_func=lambda c: "—" if c is None else c)
            systeme = c4.selectbox("Système", [None] + modele.SYSTEMES, key=f"dcal_sys_{n}",
                                   format_func=lambda s: "Déduit de l'équipement" if s is None else s)
            desc = st.text_area("Description", key=f"dcal_desc_{n}", height=90,
                                placeholder="Ce qui a été constaté, depuis quand, premières mesures prises.")
            envoi = st.form_submit_button("🚨 Émettre l'alerte", type="primary")
        if envoi:
            try:
                eid = None if code is None else int(eq.set_index("code").at[code, "id"])
                aid = ex.signaler(sev, titre, desc, eid, systeme)
                f = ex.traiter_escalades()
                st.session_state["_dcal_n"] = n + 1
                env = sum(x["envoyées"] for x in f if x["alerte"] == aid)
                ok(f"Alerte n° {aid} émise ({sev}). " + (
                    "Aucune notification pour une simple information." if sev == "Information"
                    else f"{env} message(s) de notification envoyé(s)." if env
                    else "Aucun message n'a pu être envoyé : voir l'onglet « Notifications et escalade »."))
            except ValueError as e:
                st.error(str(e))

# ============================================================================= HISTORIQUE
with t_hist:
    if al.empty:
        st.info("Aucune alerte enregistrée.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        d0 = c1.date_input("Depuis", value=(auj - timedelta(days=90)).date(), key="dcal_h_d0", format="DD/MM/YYYY")
        fs = c2.multiselect("Sévérité", modele.SEVERITES_ALERTE, key="dcal_h_s")
        ft = c3.multiselect("Statut", modele.STATUTS_ALERTE, key="dcal_h_t")
        fy = c4.multiselect("Système", modele.SYSTEMES, key="dcal_h_y")
        v = al[al["emise"] >= pd.Timestamp(d0)]
        for col, val in (("severite", fs), ("statut", ft), ("systeme", fy)):
            if val:
                v = v[v[col].isin(val)]
        v = v.assign(Équipement=v["equipement_id"].map(codes),
                     acq=(v["acquittee"] - v["emise"]).dt.total_seconds().div(60).map(lambda x: None if pd.isna(x) else format_duree(x)),
                     res=(v["resolue"] - v["emise"]).dt.total_seconds().div(60).map(lambda x: None if pd.isna(x) else format_duree(x)))
        vue = v[["id", "emise", "severite", "statut", "titre", "Équipement", "systeme", "origine", "acquittee_par", "acq",
                 "resolue_par", "res", "resolution", "description"]].rename(columns={
                     "id": "N°", "emise": "Émise le", "severite": "Sévérité", "statut": "Statut", "titre": "Objet",
                     "systeme": "Système", "origine": "Origine", "acquittee_par": "Acquittée par",
                     "acq": "Délai d'acquittement", "resolue_par": "Résolue par", "res": "Délai de résolution",
                     "resolution": "Résolution", "description": "Description"})
        st.caption(f"{len(vue)} alerte(s).")
        st.dataframe(vue.style.map(colorer_severite, subset=["Sévérité"]), hide_index=True, width="stretch", height=440,
                     column_config={"Émise le": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm"),
                                    "Objet": st.column_config.TextColumn(width="large")})
        buf = io.BytesIO()
        vue.to_excel(buf, index=False)
        st.download_button("⬇️ Exporter (Excel)", buf.getvalue(), "alertes_data_center.xlsx", key="dcal_h_dl")

# ============================================================================= NOTIFICATIONS
with t_not:
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Règles d'escalade en vigueur**")
        if pal:
            for p in sorted(pal, key=lambda p: (p.severite != "Critique", p.niveau)):
                quand = "dès l'émission" if p.delai_min == 0 else f"après {format_duree(p.delai_min)} sans acquittement"
                nb = len(ex.destinataires(p.niveau, p.severite, None, ct))
                st.markdown(f"- {ICONES[p.severite]} **{p.severite}** — {modele.NIVEAUX.get(p.niveau, p.niveau)} : {quand} "
                            f"({nb} contact(s))")
        st.caption("Délais modifiables dans « Paramètres Data Center → Escalade ». L'acquittement arrête l'escalade.")
    with c2:
        st.markdown("**Canaux d'envoi**")
        for canal, actif in canaux.items():
            st.markdown(f"- {'🟢' if actif else '⚪'} **{canal}** : {'configuré' if actif else 'non configuré — **à compléter** dans les secrets'}")
        st.caption("L'escalade est vérifiée à chaque ouverture de cette page ou du tableau de bord. Tant qu'aucune tâche "
                   "planifiée ne la déclenche (prévu au lot 5), elle n'avance pas si personne n'a l'application ouverte.")
        if agir and st.button("🔄 Vérifier les escalades maintenant", key="dcal_esc"):
            f = ex.traiter_escalades()
            ok(f"{len(f)} palier(s) d'escalade traité(s)." if f else "Aucun palier d'escalade échu.")
    section_title("JOURNAL DES NOTIFICATIONS")
    nt = ex.notifications_df()
    if nt.empty:
        st.info("Aucune notification émise.")
    else:
        nt["horodatage"] = pd.to_datetime(nt["horodatage"])
        st.dataframe(nt[["horodatage", "alerte_id", "evenement_id", "niveau", "canal", "destinataire", "statut", "detail"]]
                     .rename(columns={"horodatage": "Date", "alerte_id": "Alerte n°", "evenement_id": "Main courante n°",
                                      "niveau": "Niveau", "canal": "Canal", "destinataire": "Destinataire",
                                      "statut": "Statut", "detail": "Détail"}),
                     hide_index=True, width="stretch", height=360,
                     column_config={"Date": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm:ss")})

render_sidebar_footer("")
