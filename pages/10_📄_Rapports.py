from datetime import datetime

import streamlit as st

from utils.loader import get_data
from utils.ui import PAGE_ICON, inject_base_style, section_title, kpi_row, render_sidebar_footer
from utils.projets import get_register as get_projets_register, with_derived_columns as projets_derived
from utils.revolving import get_register as get_revolving_register, with_derived_columns as revolving_derived
from utils.conseiller import generate_recommendations
from utils.rapports import build_global_report

st.set_page_config(page_title="Rapports — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()

data = get_data()
if data is None:
    st.stop()

st.title("📄 Génération automatique de rapports")
st.caption("Rapport de synthèse PDF — assemble les indicateurs déjà calculés ailleurs dans l'application "
           "(classeur AER, suivi de projets, Fonds revolving, agent conseil), sans jamais recalculer ni "
           "inventer un chiffre.")

with st.expander("ℹ️ Ce que ce rapport contient exactement", expanded=False):
    st.markdown(
        """
Le rapport assemble, dans l'ordre : les KPI de la page d'accueil, le statut des 16 équipes terrain, le plan
d'action RH prioritaire (top 10, calculé dans le classeur), la répartition des sites par région, le suivi de
projets (si des lignes ont été saisies sur la page « Suivi de projets »), le Fonds revolving (si des dossiers
ont été saisis sur sa page), et le top 15 des recommandations de l'« Agent conseil ».

**Aucune section n'invente de donnée** : une section dont la donnée source est vide (registre de suivi de
projets ou du Fonds revolving non alimenté) l'indique explicitement plutôt que d'être simplement absente ou
de faire planter la génération.
        """
    )

projets_view = projets_derived(get_projets_register())
revolving_view = revolving_derived(get_revolving_register())
recommandations = generate_recommendations(data, projets_view, revolving_view)

section_title("APERÇU DES DONNÉES QUI SERONT INCLUSES")
kpi_row([
    ("Sites installés", str(int((data.kpis_solar or {}).get("SITES INSTALLÉS", 0) or 0)), None),
    ("Total manques RH", str((data.kpis_rh or {}).get("TOTAL MANQUES", "—")), None),
    ("Projets suivis", str(len(projets_view)), None),
    ("Dossiers Fonds revolving", str(len(revolving_view)), None),
    ("Recommandations générées", str(len(recommandations)), None),
])

st.write("")
section_title("GÉNÉRER LE RAPPORT")

if st.button("📄 Générer le rapport PDF", type="primary", key="rpt_generate"):
    with st.spinner("Génération du rapport…"):
        genere_le = datetime.now().strftime("%d/%m/%Y à %H:%M")
        try:
            pdf_bytes = build_global_report(data, projets_view, revolving_view, recommandations, genere_le)
            st.session_state["rapport_pdf_bytes"] = pdf_bytes
            st.session_state["rapport_pdf_genere_le"] = genere_le
            st.success("Rapport généré.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Échec de la génération du rapport : {exc}")

if st.session_state.get("rapport_pdf_bytes"):
    st.download_button(
        "⬇️ Télécharger le rapport (PDF)",
        st.session_state["rapport_pdf_bytes"],
        f"rapport_aer_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
        "application/pdf",
        key="rpt_download",
    )
    st.caption(f"Dernière génération : {st.session_state.get('rapport_pdf_genere_le', '—')}")

render_sidebar_footer(data.generated_on if data else "")
