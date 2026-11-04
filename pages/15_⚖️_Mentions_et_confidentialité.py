import streamlit as st

from utils.loader import get_data
from utils.storage import moteur_description
from utils.ui import PAGE_ICON, inject_base_style, section_title, render_sidebar_footer

st.set_page_config(page_title="Mentions et confidentialité — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()
data = get_data()


def _m(cle: str, defaut: str) -> str:
    try:
        return str(st.secrets["mentions"][cle])
    except Exception:  # noqa: BLE001
        return defaut


A_PRECISER = "à préciser par la Direction générale"
st.title("⚖️ Mentions légales, conditions d'utilisation et protection des données")
st.caption("Cadre de référence : loi n° 2024/017 du 23 décembre 2024 relative à la protection des données à "
           "caractère personnel au Cameroun. Les champs « à préciser » se renseignent dans les secrets de "
           "l'application (section [mentions]).")

section_title("1. ÉDITEUR ET RESPONSABLE DU TRAITEMENT")
st.markdown(f"""
- **Éditeur :** Agence d'Électrification Rurale (AER), BP 30 704 Yaoundé, Cameroun.
- **Responsable du traitement :** {_m("responsable", "le Directeur Général de l'AER")}.
- **Gestion de l'application :** {_m("gestionnaire", "Sous-Direction du Monitoring et des Statistiques Énergétiques (DGOER)")}.
- **Contact pour toute question ou demande relative aux données :** {_m("contact", A_PRECISER)}.
""")

section_title("2. CONDITIONS D'UTILISATION")
st.markdown("""
1. L'application est un **outil interne de pilotage** de l'AER. Son accès est réservé au personnel habilité,
   au moyen d'un compte nominatif ; chaque compte est personnel et ne doit pas être partagé.
2. Les informations affichées sont **confidentielles**. Leur diffusion hors de l'AER (captures, exports,
   rapports) n'est autorisée que dans le cadre des missions de l'agent et des documents validés par la hiérarchie.
3. Chaque utilisateur est responsable de l'exactitude des données qu'il saisit. Les indicateurs calculés à
   partir de saisies non validées sont **provisoires** et doivent être présentés comme tels.
4. Les accès et modifications sont **journalisés** (identifiant, date, action) à des fins de sécurité et de
   traçabilité.
5. L'AER peut suspendre un compte en cas d'usage non conforme.
""")

section_title("3. DONNÉES À CARACTÈRE PERSONNEL TRAITÉES")
st.markdown(f"""
| Catégorie | Données | Finalité | Accès |
|---|---|---|---|
| Personnel terrain | Nom, poste, antenne, équipe, mouvements | Organisation et déploiement des équipes | Tous les profils connectés |
| Paie | Catégorie, échelon, palier, enfants, éléments de rémunération | Calcul et projection de la masse salariale | Administration, Direction, DRH |
| Fonds revolving | Agent en charge, localité, montants | Suivi du recouvrement (PERACE) | Profils connectés |
| Comptes | Identifiant, nom, rôle, journal des actions | Sécurité et traçabilité | Administrateur |

- **Base du traitement :** exécution des missions de service public de l'AER et gestion de la relation de travail.
- **Durée de conservation :** {_m("conservation", A_PRECISER)}.
- **Droits des personnes :** accès, rectification, opposition et effacement, dans les conditions prévues par la
  loi n° 2024/017, en s'adressant au contact indiqué au point 1.
""")

section_title("4. HÉBERGEMENT, SÉCURITÉ ET TRACEURS")
st.markdown(f"""
- **Hébergement de l'application :** Streamlit Community Cloud (Snowflake Inc., États-Unis). Les données
  saisies et les fichiers importés sont donc traités hors du Cameroun tant que l'application n'est pas
  hébergée sur le Data Center de l'AER (procédure décrite dans `DEPLOIEMENT.md`).
- **Stockage des registres :** {moteur_description()}.
- **Sécurité :** connexion obligatoire par compte nominatif ; mots de passe conservés uniquement sous forme
  d'empreinte chiffrée (PBKDF2-SHA256) ; blocage temporaire après cinq échecs ; droits différenciés par rôle ;
  journal des actions ; échanges chiffrés (HTTPS).
- **Traceurs :** l'hébergeur Streamlit Cloud dépose ses propres cookies de mesure d'audience et de
  fonctionnement (notamment Google Analytics, Google Tag Manager, Segment, Heap, Datadog), sur lesquels l'AER
  n'a pas la main. L'application elle-même ne dépose aucun cookie publicitaire. L'hébergement sur le Data
  Center de l'AER supprime ces traceurs tiers.
""")

section_title("5. PROPRIÉTÉ ET SOURCES")
st.markdown("""
Les données, analyses et documents produits sont la propriété de l'AER. Chaque indicateur repris dans le
« Dossier de plaidoyer » est accompagné de sa source (classeur, registre ou import) et de sa date.
""")

render_sidebar_footer(data.generated_on if data else "")
