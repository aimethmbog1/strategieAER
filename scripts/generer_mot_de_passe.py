"""Génère l'empreinte d'un mot de passe pour les secrets Streamlit (section [auth.users.<identifiant>]).

Usage :  python scripts/generer_mot_de_passe.py
Le mot de passe saisi n'est ni affiché ni enregistré ; seule l'empreinte est imprimée.
"""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils.auth import ROLES, hacher_mot_de_passe  # noqa: E402

login = input("Identifiant (minuscules, sans espace) : ").strip().lower()
nom = input("Nom affiché : ").strip()
role = input(f"Rôle {list(ROLES)} : ").strip()
if role not in ROLES:
    sys.exit(f"Rôle inconnu : {role}")
mdp = getpass.getpass("Mot de passe (12 caractères minimum) : ")
if len(mdp) < 12:
    sys.exit("Mot de passe trop court (12 caractères minimum).")
if mdp != getpass.getpass("Confirmez : "):
    sys.exit("Les deux saisies diffèrent.")
print("\nÀ coller dans Settings → Secrets (Streamlit Cloud) ou .streamlit/secrets.toml :\n")
print(f"[auth.users.{login}]\nnom = \"{nom}\"\nrole = \"{role}\"\npassword_hash = \"{hacher_mot_de_passe(mdp)}\"")
