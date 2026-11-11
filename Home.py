"""Point d'entrée de l'application : navigation par grands domaines (les pages sont dans le dossier vues/ : un dossier « pages/ » ferait basculer Streamlit dans son ancien mode de navigation)."""
from pathlib import Path

import streamlit as st

from utils.auth import ROLES_PAIE, auth_desactivee, require_login, role
from utils.ui import PAGE_ICON

st.set_page_config(page_title="AER — Pilotage", page_icon=PAGE_ICON, layout="wide")

# Écran de connexion avant d'afficher le menu (les pages vérifient aussi l'accès elles-mêmes).
if not auth_desactivee() and not st.session_state.get("auth_user"):
    require_login()

RACINE = Path(__file__).resolve().parent


def P(prefixe: str, titre: str, icone: str, defaut: bool = False):
    f = next((p for p in sorted((RACINE / "vues").glob("*.py")) if p.name.startswith(prefixe)), None)
    if f is None:
        return None
    url = f.stem.split("_", 2)[-1] if f.stem.count("_") >= 2 else f.stem
    return st.Page(f"vues/{f.name}", title=titre, icon=icone, default=defaut, url_path=None if defaut else url)


r = role()
MENU = {
    "Pilotage": [
        P("00_", "Tableau de bord", "🏠", defaut=True),
        P("01_", "Vue d'ensemble détaillée", "📊"),
        P("19_", "Alertes", "🚨"),
        P("10_", "Rapports", "📄"),
        P("20_", "Dossier de plaidoyer", "🎯"),
        P("11_", "Agent conseil", "🤖"),
    ],
    "Parc solaire et exploitation": [
        P("1_", "Carte d'électrification", "🗺️"),
        P("2_", "Parc solaire", "🛰️"),
        P("4_", "Répartition régionale", "🌍"),
        P("23_", "GMAO — Maintenance", "🔧"),
        P("17_", "Supervision des centrales", "📡"),
        P("24_", "FusionSolar en ligne", "☀️"),
    ],
    "Data Center FM800": [
        P("30_", "Tableau de bord Data Center", "🖥️"),
        P("31_", "Registre des actifs", "🗄️"),
        P("32_", "Inspections", "📝"),
        P("33_", "Maintenance", "🛠️"),
        P("34_", "Alertes", "🚨"),
        P("35_", "Main courante et passation", "📒"),
        P("36_", "Analyse des pannes", "🔬"),
        P("37_", "Rapports Data Center", "📄"),
        P("38_", "Paramètres Data Center", "⚙️"),
    ] if (auth_desactivee() or r in {"admin", "direction", "sdmse", "technicien", "lecteur"}) else [],
    "Commercial et comptage": [
        P("18_", "Recettes et abonnés", "💵"),
        P("25_", "Clients institutionnels", "🏢"),
        P("21_", "Recharges Data Center", "🔋"),
        P("8_", "Statistiques compteurs", "🔌"),
    ],
    "Projets et financements": [
        P("9_", "Suivi de projets", "📌"),
        P("7_", "Fonds revolving", "💰"),
        P("16_", "Suivi budgétaire", "📒"),
    ],
    "Ressources": [
        P("3_", "Équipes terrain", "👷"),
        P("5_", "Organigramme", "🏢"),
        P("13_", "Masse salariale", "💼") if (auth_desactivee() or r in ROLES_PAIE) else None,
        P("12_", "Parc automobile", "🚗"),
    ],
    "Administration": [
        P("14_", "Administration", "🛡️") if (auth_desactivee() or r == "admin") else None,
        P("22_", "Explorateur de la base", "🗄️") if (auth_desactivee() or r in {"admin", "direction", "sdmse"}) else None,
        P("6_", "Notes et méthodologie", "📝"),
        P("15_", "Mentions et confidentialité", "⚖️"),
    ],
}
MENU = {k: [p for p in v if p is not None] for k, v in MENU.items()}
if not auth_desactivee() and r == "technicien":  # le technicien ne voit que le module Data Center
    MENU = {"Data Center FM800": MENU["Data Center FM800"]}
try:
    nav = st.navigation({k: v for k, v in MENU.items() if v}, expanded=True)
except TypeError:  # versions sans le paramètre « expanded »
    nav = st.navigation({k: v for k, v in MENU.items() if v})
nav.run()
