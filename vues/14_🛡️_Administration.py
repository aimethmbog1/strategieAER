import pandas as pd
import streamlit as st

from utils.auth import ROLES, _comptes, require_role
from utils.loader import get_data
from utils.storage import (
    etat_registres, lire_journal, moteur_description, moteur_ephemere, restaurer, sauvegarde_complete,
)
from utils.ui import PAGE_ICON, inject_base_style, section_title, kpi_row, render_sidebar_footer

st.set_page_config(page_title="Administration — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()
require_role({"admin"}, "l'administration")
data = get_data()

st.title("🛡️ Administration")
st.caption("Stockage des registres, sauvegardes, comptes et journal des actions.")

section_title("STOCKAGE DES DONNÉES SAISIES")
etat = etat_registres()
kpi_row([
    ("Moteur de stockage", moteur_description(), None),
    ("Registres enregistrés", f"{(etat['Dernière mise à jour'] != '—').sum()} / {len(etat)}", None),
    ("Volume total", f"{etat['Taille (Ko)'].sum():,.1f} Ko".replace(",", " "), None),
])
if moteur_ephemere():
    st.error("⚠️ Hébergement Streamlit Community Cloud sans base externe : les registres sont effacés à chaque "
             "redémarrage de l'application. Téléchargez une sauvegarde complète après chaque séance de saisie, "
             "ou déclarez une base PostgreSQL dans les secrets (`[database] url = \"postgresql+psycopg2://…\"`), "
             "idéalement hébergée sur le Data Center de l'AER.")
st.dataframe(etat, width="stretch", hide_index=True)

c1, c2 = st.columns(2)
with c1:
    st.markdown("**Sauvegarde complète**")
    st.caption("Un classeur Excel : tous les registres (format restaurable + version lisible) et le journal.")
    if st.button("Préparer la sauvegarde", width="stretch"):
        st.session_state["admin_sauvegarde"] = sauvegarde_complete()
    if st.session_state.get("admin_sauvegarde"):
        st.download_button("⬇️ Télécharger la sauvegarde", st.session_state["admin_sauvegarde"],
                           f"sauvegarde_aer_{pd.Timestamp.now():%Y%m%d_%H%M}.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
with c2:
    st.markdown("**Restauration**")
    st.caption("Remplace les registres par ceux de la sauvegarde choisie. L'opération est journalisée.")
    f = st.file_uploader("Sauvegarde (.xlsx)", type=["xlsx"], key="admin_restore")
    if f is not None and st.button("Restaurer cette sauvegarde", type="primary", width="stretch"):
        try:
            faits = restaurer(f)
            st.success(f"{len(faits)} registre(s) restauré(s) : {', '.join(faits) or '—'}")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Restauration impossible : {exc}")

section_title("COMPTES DÉCLARÉS")
comptes = _comptes()
if comptes:
    st.dataframe(pd.DataFrame([{"Identifiant": k, "Nom": v.get("nom", ""), "Rôle": ROLES.get(v.get("role"), v.get("role"))}
                               for k, v in comptes.items()]), width="stretch", hide_index=True)
else:
    st.info("Aucun compte déclaré dans les secrets (session de développement).")
st.caption("Les comptes se gèrent dans les secrets Streamlit (Manage app → Settings → Secrets). Empreinte d'un "
           "nouveau mot de passe : `python scripts/generer_mot_de_passe.py`. Rôles : "
           + ", ".join(f"`{k}` ({v})" for k, v in ROLES.items()) + ".")

section_title("JOURNAL DES ACTIONS")
j = lire_journal()
c1, c2, c3 = st.columns(3)
fu = c1.multiselect("Utilisateur", sorted(j["Utilisateur"].dropna().unique()))
fa = c2.text_input("Action contient")
periode = c3.selectbox("Période", ["Tout", "Aujourd'hui", "7 derniers jours", "30 derniers jours"])
v = j.copy()
if fu:
    v = v[v["Utilisateur"].isin(fu)]
if fa:
    v = v[v["Action"].str.contains(fa, case=False, na=False)]
if periode != "Tout" and not v.empty:
    jours = {"Aujourd'hui": 0, "7 derniers jours": 7, "30 derniers jours": 30}[periode]
    seuil = (pd.Timestamp.now().normalize() - pd.Timedelta(days=jours)).isoformat()
    v = v[v["Horodatage"] >= seuil]
st.dataframe(v, width="stretch", hide_index=True, height=420)
st.download_button("⬇️ Exporter le journal (CSV)", v.to_csv(index=False).encode("utf-8"), "journal_aer.csv", "text/csv")

render_sidebar_footer(data.generated_on if data else "")
