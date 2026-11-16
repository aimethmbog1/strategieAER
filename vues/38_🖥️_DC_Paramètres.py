import streamlit as st

from dc import depot, exploitation as ex, imports, modele, notifications
from dc.regles import format_duree
from dc.ui import ROLES_GESTION, ROLES_SENSIBLE, bandeau, exiger_lecture, initialiser, peut, style
from utils.ui import PAGE_ICON, inject_base_style, render_sidebar_footer

st.set_page_config(page_title="Data Center — paramètres — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()
exiger_lecture()
initialiser()
style()
bandeau("Paramètres du module Data Center",
        "Seuils d'alerte, listes de contrôle, escalade des alertes, données sensibles et journal d'audit")

if st.session_state.get("_dcp_ok"):
    st.success("💾 " + st.session_state.pop("_dcp_ok"))
gestion = peut(ROLES_GESTION)


def ok(msg):
    st.session_state["_dcp_ok"] = msg
    st.rerun()


t_s, t_c, t_esc, t_sens, t_aud = st.tabs(["🎚️ Seuils", "✅ Listes de contrôle", "📣 Escalade et notifications",
                                              "🔐 Cartographie et constats", "🧾 Journal d'audit"])

with t_s:
    st.caption("Une mesure hors de la plage d'avertissement crée un avertissement ; hors de la plage critique, un écart "
               "critique. Laisser une borne vide la désactive. La colonne « Référence » indique la norme ou le document "
               "d'origine de chaque seuil.")
    s = depot.seuils_df()
    ed = st.data_editor(s, hide_index=True, width="stretch", key="dcp_s", disabled=not gestion or ["grandeur", "libelle", "unite", "reference"],
                        column_config={"grandeur": "Clé", "libelle": st.column_config.TextColumn("Grandeur", width="medium"),
                                       "unite": "Unité", "avert_min": "Avert. min", "avert_max": "Avert. max",
                                       "crit_min": "Critique min", "crit_max": "Critique max",
                                       "reference": st.column_config.TextColumn("Référence", width="large")})
    if gestion and st.button("💾 Enregistrer les seuils", key="dcp_s_ok"):
        depot.modifier_seuils(ed)
        ok("Seuils enregistrés.")

with t_c:
    c = depot.controles(actifs_seulement=False)
    c1, c2 = st.columns(2)
    fc = c1.multiselect("Cible", sorted(c["cible"].unique()), key="dcp_c_c")
    ff = c2.multiselect("Fréquence", modele.FREQUENCES, key="dcp_c_f")
    v = c
    if fc:
        v = v[v["cible"].isin(fc)]
    if ff:
        v = v[v["frequence"].isin(ff)]
    st.caption(f"{len(v)} contrôle(s). Les listes « RESEAU » s'appliquent à tous les équipements réseau Huawei et la "
               "liste « SALLE » au micro-module FM800. Les fréquences des listes réseau et salle sont proposées "
               "(absentes du document source) : ajuste-les si besoin.")
    ed = st.data_editor(v[["id", "cible", "phase", "point", "commande", "normal", "a_signaler", "frequence", "grandeur",
                           "actif", "source"]], hide_index=True, width="stretch", height=480, key="dcp_c",
                        disabled=["id", "cible", "phase", "point", "commande", "normal", "a_signaler", "grandeur", "source"]
                        if gestion else True,
                        column_config={"id": None, "frequence": st.column_config.SelectboxColumn("Fréquence", options=modele.FREQUENCES),
                                       "actif": st.column_config.CheckboxColumn("Actif")})
    if gestion and st.button("💾 Enregistrer", key="dcp_c_ok"):
        depot.modifier_controles(ed)
        ok("Listes de contrôle mises à jour.")

with t_esc:
    st.caption("Une alerte non acquittée est notifiée niveau par niveau. Le délai se compte depuis l'émission de "
               "l'alerte ; 0 signifie « dès l'émission ». L'acquittement arrête l'escalade. Délais validés le "
               "11/11/2026 : critique 15 min puis 30 min, avertissement 4 h. Une simple information n'est jamais notifiée.")
    rg = ex.regles_df()
    rg["Destinataires"] = rg["niveau"].map(modele.NIVEAUX)
    rg["Contacts actifs"] = [len(ex.destinataires(int(r.niveau), r.severite, None)) for r in rg.itertuples()]
    ed = st.data_editor(rg[["id", "severite", "niveau", "Destinataires", "delai_min", "actif", "Contacts actifs"]],
                        hide_index=True, width="stretch", key="dcp_esc",
                        disabled=True if not gestion else ["id", "severite", "niveau", "Destinataires", "Contacts actifs"],
                        column_config={"id": None, "severite": "Sévérité", "niveau": "Niveau",
                                       "delai_min": st.column_config.NumberColumn("Délai sans acquittement (min)", min_value=0, step=5),
                                       "actif": st.column_config.CheckboxColumn("Actif")})
    if gestion and st.button("💾 Enregistrer les règles d'escalade", key="dcp_esc_ok"):
        try:
            ex.modifier_regles(ed)
            ok("Règles d'escalade enregistrées.")
        except ValueError as e:
            st.error(str(e))
    if (rg["Contacts actifs"] == 0).any():
        st.warning("Certains niveaux n'ont aucun contact actif : leurs notifications ne partiront pas. Annuaire **à "
                   "compléter** dans « Main courante et passation → Annuaire ».")
    st.markdown("**Canaux d'envoi**")
    for canal, actif in notifications.canaux_configures().items():
        st.markdown(f"- {'🟢' if actif else '⚪'} **{canal}** : {'configuré' if actif else 'non configuré'}")
    with st.expander("Comment configurer le courriel et Telegram"):
        st.markdown("""Les identifiants d'envoi ne sont jamais écrits dans le code ni dans le dépôt GitHub. Ils se déclarent dans
*Manage app → Settings → Secrets* (Streamlit Cloud) :

```toml
[smtp]
host = "smtp.exemple.cm"
port = 587
user = "alertes@exemple.cm"
password = "…"
expediteur = "Data Center AER <alertes@exemple.cm>"

[telegram]
bot_token = "123456:ABC…"

[dc]
url = "https://strategiedeploiementaer.streamlit.app/DC_Alertes"
```

**Telegram** : créer un bot avec @BotFather (il fournit le jeton) ; chaque destinataire écrit une fois au bot, puis son
identifiant de conversation se lit à l'adresse `https://api.telegram.org/bot<jeton>/getUpdates` (champ `chat.id`) et se
saisit dans l'annuaire. Pour un groupe, ajouter le bot au groupe et saisir l'identifiant du groupe.""")

with t_sens:
    if not peut(ROLES_SENSIBLE):
        st.info("🔒 Réservé aux profils Administrateur et Monitoring & statistiques.")
    else:
        st.caption("Le plan d'adressage IP et les constats de la cartographie réseau sont des informations sensibles : "
                   "ils ne sont jamais écrits dans le code ni dans le dépôt GitHub. Importe le document Word de "
                   "cartographie : ses tableaux sont lus et enregistrés dans la base, visibles de ces seuls profils.")
        f = st.file_uploader("Cartographie réseau (.docx)", type=["docx"], key="dcp_carto")
        if f is not None:
            ip, cst = imports.lire_cartographie(f.getvalue())
            st.write(f"{len(ip)} plage(s) d'adressage et {len(cst)} constat(s) détectés.")
            if st.button("📥 Importer", type="primary", key="dcp_imp", disabled=ip.empty and cst.empty):
                b = depot.remplacer_donnees_sensibles(ip, cst, f.name)
                ok(f"Import réalisé : {b['plages_ip']} plage(s) d'adressage, {b['constats_ajoutes']} nouveau(x) constat(s).")
        cst = depot.constats()
        if len(cst):
            st.markdown("**Constats suivis comme actions correctives**")
            ed = st.data_editor(cst[["id", "numero", "nature", "constat", "equipements", "statut", "action", "responsable", "echeance"]],
                                hide_index=True, width="stretch", height=420, key="dcp_cst",
                                disabled=["id", "numero", "nature", "constat", "equipements"],
                                column_config={"id": None,
                                               "statut": st.column_config.SelectboxColumn("Statut", options=["Ouvert", "En cours", "Clôturé", "Accepté (risque assumé)"]),
                                               "echeance": st.column_config.DateColumn("Échéance", format="DD/MM/YYYY")})
            if st.button("💾 Enregistrer les constats", key="dcp_cst_ok"):
                depot.modifier_constats(ed)
                ok("Constats mis à jour.")
        ip = depot.reseau_ip()
        if len(ip):
            with st.expander("Plan d'adressage IP"):
                st.dataframe(ip.drop(columns="id"), hide_index=True, width="stretch")

with t_aud:
    if not peut(ROLES_GESTION):
        st.info("🔒 Réservé aux profils Administrateur et Monitoring & statistiques.")
    else:
        a = depot.journal_audit(1000)
        st.caption("Toutes les créations, modifications, inspections et imports du module, avec leur auteur.")
        st.dataframe(a.drop(columns="id"), hide_index=True, width="stretch", height=480,
                     column_config={"horodatage": st.column_config.DatetimeColumn("Date", format="DD/MM/YYYY HH:mm:ss")})

render_sidebar_footer("")
