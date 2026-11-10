import streamlit as st

from utils.alertes import GRAVITES, calculer_alertes, envoyer_recapitulatif, smtp_configure
from utils.auth import journaliser, peut_modifier
from utils.data import RED, AMBER, BLUE, GREY
from utils.loader import get_data
from utils.ui import PAGE_ICON, inject_base_style, section_title, kpi_row, render_sidebar_footer, style_map

from utils.parametres import memoriser, valeur
st.set_page_config(page_title="Alertes — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()
data = get_data()
if data is None:
    st.stop()

st.title("🚨 Alertes")
st.caption("Points nécessitant une action, détectés automatiquement dans les registres et le classeur source : "
           "véhicules, projets bloqués, fonds revolving, équipes, paie et recrutement, centrales silencieuses, "
           "exécution budgétaire, fraîcheur des données.")

with st.expander("⚙️ Seuils"):
    c = st.columns(6)
    sv = valeur("alertes", "seuils", {})
    seuils = {
        "projet_jours": c[0].number_input("Projet sans mouvement (jours)", 7, 365, int(sv.get("projet_jours", 60))),
        "vidange_mois": c[1].number_input("Intervalle de vidange (mois)", 1, 24, int(sv.get("vidange_mois", 6))),
        "age_reforme": c[2].number_input("Âge de réforme (ans)", 3, 20, int(sv.get("age_reforme", 7))),
        "essai_jours": c[3].number_input("Fin d'essai à venir (jours)", 7, 120, int(sv.get("essai_jours", 30))),
        "silence_jours": c[4].number_input("Centrale silencieuse (jours)", 1, 30, int(sv.get("silence_jours", 2))),
        "fraicheur_jours": c[5].number_input("Données sources anciennes (jours)", 7, 365, int(sv.get("fraicheur_jours", 60))),
    }
    memoriser("alertes", "seuils", seuils)
    st.caption("💾 Seuils enregistrés dans la base : ils s'appliquent à tous les utilisateurs.")

al = calculer_alertes(data, seuils)
kpi_row([(g, str(int((al["Gravité"] == g).sum())) if not al.empty else "0", None) for g in GRAVITES])

if al.empty:
    st.success("Aucune alerte avec les seuils actuels.")
else:
    f = st.multiselect("Domaines", sorted(al["Domaine"].unique()))
    v = al[al["Domaine"].isin(f)] if f else al
    coul = {"Critique": f"background-color:#FBE4E4;color:{RED};font-weight:700",
            "Élevée": f"background-color:#FBEEDD;color:{AMBER};font-weight:700",
            "Moyenne": f"color:{BLUE};font-weight:600", "Information": f"color:{GREY}"}
    st.dataframe(style_map(v.style, lambda x: coul.get(x, ""), subset=["Gravité"]), width="stretch", hide_index=True,
                 height=min(80 + 36 * len(v), 600))
    st.download_button("⬇️ Exporter les alertes (CSV)", v.to_csv(index=False).encode("utf-8"), "alertes_aer.csv", "text/csv")

    section_title("ENVOI DU RÉCAPITULATIF PAR COURRIEL")
    if not smtp_configure():
        st.caption("Envoi désactivé : déclarez un serveur de messagerie dans les secrets "
                   "(`[smtp] host, port, user, password, expediteur`) pour l'activer.")
    elif peut_modifier():
        dest = st.text_input("Destinataires (séparés par des virgules)")
        if st.button("Envoyer le récapitulatif", disabled=not dest.strip()):
            try:
                liste = [d.strip() for d in dest.split(",") if d.strip()]
                st.success(envoyer_recapitulatif(v, liste))
                journaliser("Envoi du récapitulatif d'alertes", ", ".join(liste))
            except Exception as exc:  # noqa: BLE001
                st.error(f"Envoi impossible : {exc}")

render_sidebar_footer(data.generated_on)
