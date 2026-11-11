import pandas as pd
import streamlit as st

from utils.data import RED, AMBER, BLUE
from utils.loader import get_data
from utils.ui import PAGE_ICON, inject_base_style, section_title, kpi_row, render_sidebar_footer
from utils.projets import get_register as get_projets_register, with_derived_columns as projets_derived
from utils.revolving import get_register as get_revolving_register, with_derived_columns as revolving_derived
from utils.conseiller import generate_recommendations, explain_rules

st.set_page_config(page_title="Agent conseil — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()

data = get_data()
if data is None:
    st.stop()

st.title("🤖 Agent conseil — orientation RH & projets")
st.caption("Recommandations priorisées pour accélérer la réactivité des agents, suivre les projets en "
           "cours, reprendre les projets à l'arrêt et relancer l'électrification en NOSO / Extrême-Nord.")

with st.expander("ℹ️ Comment cet agent fonctionne — à lire avant de suivre ses conseils", expanded=False):
    st.markdown(
        """
**Ce n'est pas un chatbot ni un modèle de langage.** C'est un **moteur de règles déterministe** : chaque
recommandation ci-dessous est produite par une règle écrite à l'avance (listées plus bas) et **toujours
reliée à un chiffre réel** déjà présent dans l'application — jamais une affirmation sans le nombre qui la
justifie, jamais une donnée inventée.

**Pourquoi ce choix plutôt qu'un agent conversationnel branché sur une IA générative :** gratuit, instantané,
aucune clé API ni secret à gérer sur un déploiement public, et un résultat entièrement traçable. Cette page
peut évoluer vers un habillage conversationnel si une clé API est fournie plus tard — sans que la logique
ci-dessous change.

**Limite à connaître** : les recommandations de « Suivi de projets » et « Fonds revolving » ne portent que
sur ce qui a été **saisi** sur ces pages. Un registre vide ou pas à jour donne une impression artificielle
de calme — l'absence d'alerte ne veut pas dire « tout va bien ».
        """
    )

projets_view = projets_derived(get_projets_register())
revolving_view = revolving_derived(get_revolving_register())
recommandations = generate_recommendations(data, projets_view, revolving_view)

n_haute = sum(1 for r in recommandations if r["priorite"] == "Haute")
n_moyenne = sum(1 for r in recommandations if r["priorite"] == "Moyenne")
n_info = sum(1 for r in recommandations if r["priorite"] == "Info")

section_title("SYNTHÈSE DES RECOMMANDATIONS")
kpi_row([
    ("Recommandations totales", str(len(recommandations)), None),
    ("Priorité haute", str(n_haute), None),
    ("Priorité moyenne", str(n_moyenne), None),
    ("Informatives", str(n_info), None),
])

st.write("")
section_title("FILTRES")
c1, c2, c3 = st.columns(3)
categories = sorted({r["categorie"] for r in recommandations})
f_categorie = c1.multiselect("Catégorie", categories, default=[], key="ac_cat")
f_priorite = c2.multiselect("Priorité", ["Haute", "Moyenne", "Info"], default=[], key="ac_prio")
f_recherche = c3.text_input("Rechercher un mot-clé (site, région, antenne…)", key="ac_search")

vues = recommandations
if f_categorie:
    vues = [r for r in vues if r["categorie"] in f_categorie]
if f_priorite:
    vues = [r for r in vues if r["priorite"] in f_priorite]
if f_recherche:
    needle = f_recherche.lower()
    vues = [r for r in vues if needle in r["titre"].lower() or needle in r["detail"].lower()]

st.caption(f"{len(vues)} recommandation(s) affichée(s) sur {len(recommandations)}")

st.write("")
section_title("RECOMMANDATIONS")

PRIORITE_COLOR = {"Haute": RED, "Moyenne": AMBER, "Info": BLUE}
PRIORITE_ICON = {"Haute": "🔴", "Moyenne": "🟠", "Info": "🔵"}

if not vues:
    st.info("Aucune recommandation ne correspond à ces filtres.")
else:
    for r in vues:
        with st.container(border=True):
            st.markdown(
                f"{PRIORITE_ICON.get(r['priorite'], '⚪')} **[{r['priorite']}] {r['categorie']}** — {r['titre']}"
            )
            st.caption(r["detail"])
            st.caption(f"Source : {r['source']}")

st.write("")
st.download_button(
    "⬇️ Télécharger ces recommandations (CSV)",
    pd.DataFrame(vues).to_csv(index=False).encode("utf-8") if vues else b"",
    "recommandations_agent_conseil.csv", "text/csv",
    disabled=not vues,
)

st.write("")
with st.expander("📖 Règles utilisées par ce moteur — transparence totale"):
    for titre, description in explain_rules():
        st.markdown(f"**{titre}** — {description}")

render_sidebar_footer(data.generated_on if data else "")
