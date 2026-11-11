"""
Contrôle d'accès — comptes nominatifs, rôles, journal des actions.

Les comptes sont déclarés dans les secrets Streamlit (jamais dans le code ni
dans le dépôt GitHub) :

    # .streamlit/secrets.toml  (local)  ou  Settings → Secrets  (Streamlit Cloud)
    [auth.users.athierry]
    nom = "Aime Thierry"
    role = "admin"
    password_hash = "pbkdf2_sha256$310000$<sel>$<empreinte>"

Les empreintes se génèrent avec :  python scripts/generer_mot_de_passe.py
Les mots de passe ne sont jamais stockés en clair.

Rôles :
  admin      — tout, y compris l'administration (sauvegardes, journal)
  direction  — consultation de tout (paie comprise), modification des registres
  drh        — paie et personnel, modification des registres
  sdmse      — modules techniques et statistiques, modification des registres
  lecteur    — consultation seule, hors paie

Pour les tests automatisés et le développement local uniquement, la variable
d'environnement AER_AUTH_DISABLED=1 ouvre une session « admin » fictive.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets as _secrets
import time

import streamlit as st

ROLES = {
    "admin": "Administrateur",
    "direction": "Direction",
    "drh": "Ressources humaines",
    "sdmse": "Monitoring & statistiques",
    "technicien": "Technicien Data Center",
    "lecteur": "Lecteur",
}
ROLES_EDITION = {"admin", "direction", "drh", "sdmse"}
ROLES_PAIE = {"admin", "direction", "drh"}
MAX_ESSAIS = 5
BLOCAGE_S = 60
ITERATIONS = 310_000


# ------------------------------------------------------------------ mots de passe
def hacher_mot_de_passe(mot_de_passe: str, iterations: int = ITERATIONS) -> str:
    sel = _secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", mot_de_passe.encode("utf-8"), bytes.fromhex(sel), iterations)
    return f"pbkdf2_sha256${iterations}${sel}${dk.hex()}"


def verifier_mot_de_passe(mot_de_passe: str, empreinte: str) -> bool:
    try:
        algo, it, sel, attendu = empreinte.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", mot_de_passe.encode("utf-8"), bytes.fromhex(sel), int(it))
        return hmac.compare_digest(dk.hex(), attendu)
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------------ comptes
def _comptes() -> dict:
    try:
        users = st.secrets["auth"]["users"]
        return {k: dict(v) for k, v in users.items()}
    except Exception:  # noqa: BLE001
        return {}


def auth_desactivee() -> bool:
    return os.environ.get("AER_AUTH_DISABLED") == "1"


def utilisateur() -> dict | None:
    if auth_desactivee():
        return {"login": "dev", "nom": "Session de développement", "role": "admin"}
    return st.session_state.get("auth_user")


def role() -> str | None:
    u = utilisateur()
    return u["role"] if u else None


def peut_modifier() -> bool:
    return role() in ROLES_EDITION


def peut_voir_paie() -> bool:
    return role() in ROLES_PAIE


# ------------------------------------------------------------------ écrans
def _ecran_configuration():
    st.title("🔒 Accès protégé — configuration requise")
    st.error("Aucun compte n'est déclaré : l'application reste fermée tant que les comptes ne sont pas "
             "configurés, pour protéger les données du personnel et de la paie.")
    st.markdown(
        "**Pour l'administrateur :**\n"
        "1. Sur votre ordinateur, générez l'empreinte d'un mot de passe : "
        "`python scripts/generer_mot_de_passe.py`\n"
        "2. Sur Streamlit Cloud : *Manage app → Settings → Secrets*, collez par exemple :\n"
        "```toml\n[auth.users.athierry]\nnom = \"Prénom NOM\"\nrole = \"admin\"\n"
        "password_hash = \"pbkdf2_sha256$310000$...\"\n```\n"
        "3. Enregistrez : l'application redémarre et affiche l'écran de connexion.\n\n"
        "Rôles disponibles : `admin`, `direction`, `drh`, `sdmse`, `lecteur`.")
    st.stop()


def _ecran_connexion(comptes: dict):
    st.markdown("<div style='height:6vh'></div>", unsafe_allow_html=True)
    _, c, _ = st.columns([1, 1.2, 1])
    with c:
        st.markdown("## ☀️ Agence d'Électrification Rurale")
        st.caption("Tableau de bord — Parc solaire, ressources humaines et pilotage. Accès réservé au personnel "
                   "habilité de l'AER.")
        bloque_jusqua = st.session_state.get("auth_bloque_jusqua", 0)
        if time.time() < bloque_jusqua:
            st.error(f"Trop de tentatives. Réessayez dans {int(bloque_jusqua - time.time()) + 1} s.")
            st.stop()
        with st.form("connexion", clear_on_submit=False):
            login = st.text_input("Identifiant").strip().lower()
            mdp = st.text_input("Mot de passe", type="password")
            ok = st.form_submit_button("Se connecter", type="primary", width="stretch")
        if ok:
            compte = comptes.get(login)
            if compte and verifier_mot_de_passe(mdp, str(compte.get("password_hash", ""))) \
                    and compte.get("role") in ROLES:
                st.session_state["auth_user"] = {"login": login, "nom": compte.get("nom", login),
                                                 "role": compte["role"]}
                st.session_state.pop("auth_echecs", None)
                journaliser("Connexion", "")
                st.rerun()
            else:
                n = st.session_state.get("auth_echecs", 0) + 1
                st.session_state["auth_echecs"] = n
                journaliser("Échec de connexion", f"identifiant saisi : {login[:40]}", login=login or "?")
                if n >= MAX_ESSAIS:
                    st.session_state["auth_bloque_jusqua"] = time.time() + BLOCAGE_S
                    st.session_state["auth_echecs"] = 0
                time.sleep(1)
                st.error("Identifiant ou mot de passe incorrect.")
        st.caption("En vous connectant, vous acceptez les règles d'usage décrites dans la page "
                   "« Mentions et confidentialité ». Les accès sont journalisés.")
    st.stop()


def require_login() -> dict:
    """À appeler en tête de chaque page (fait automatiquement par ui.inject_base_style)."""
    if auth_desactivee():
        return utilisateur()
    u = st.session_state.get("auth_user")
    if u:
        _barre_utilisateur(u)
        return u
    comptes = _comptes()
    if not comptes:
        _ecran_configuration()
    _ecran_connexion(comptes)


def require_role(roles: set[str], libelle: str = "cette page"):
    if role() not in roles:
        st.warning(f"🔒 Votre profil ({ROLES.get(role(), '—')}) ne donne pas accès à {libelle}.")
        st.stop()


def _barre_utilisateur(u: dict):
    with st.sidebar:
        st.markdown(f"👤 **{u['nom']}**  \n<small>{ROLES.get(u['role'], u['role'])}</small>",
                    unsafe_allow_html=True)
        if st.button("Se déconnecter", key="auth_logout", width="stretch"):
            journaliser("Déconnexion", "")
            for k in ("auth_user",):
                st.session_state.pop(k, None)
            st.rerun()


# ------------------------------------------------------------------ journal
def journaliser(action: str, detail: str = "", login: str | None = None) -> None:
    """Trace une action dans le journal durable (best effort : n'interrompt jamais la page)."""
    try:
        from .storage import ecrire_journal
        u = utilisateur() or {}
        ecrire_journal(login or u.get("login", "?"), u.get("role", ""), action, detail)
    except Exception:  # noqa: BLE001
        pass
