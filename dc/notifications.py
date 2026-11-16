"""Envoi des notifications du module Data Center : courriel (SMTP) et Telegram.

Aucun secret dans le code : la configuration est lue dans les secrets Streamlit, ou à défaut dans les
variables d'environnement (utile pour une tâche planifiée hors Streamlit).

    # Settings → Secrets (Streamlit Cloud) ou .streamlit/secrets.toml (local)
    [smtp]                      # déjà utilisé par la page « Alertes » générale
    host = "smtp.exemple.cm"
    port = 587
    user = "alertes@exemple.cm"
    password = "…"
    expediteur = "Data Center AER <alertes@exemple.cm>"

    [telegram]
    bot_token = "123456:ABC…"   # jeton du bot créé avec @BotFather

    [dc]
    url = "https://strategiedeploiementaer.streamlit.app/DC_Alertes"   # lien rappelé dans les messages

Variables d'environnement équivalentes : DC_SMTP_HOST, DC_SMTP_PORT, DC_SMTP_USER, DC_SMTP_PASSWORD,
DC_SMTP_EXPEDITEUR, DC_TELEGRAM_TOKEN, DC_URL.
"""
from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from email.mime.text import MIMEText

DELAI_S = 10
URL_DEFAUT = "https://strategiedeploiementaer.streamlit.app/DC_Alertes"


@dataclass(frozen=True)
class Resultat:
    statut: str          # « Envoyée », « Échec » ou « Canal non configuré »
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.statut == "Envoyée"


def _secret(section: str, cle: str, env: str, defaut=None):
    try:
        import streamlit as st
        v = st.secrets[section][cle]
        if v not in (None, ""):
            return v
    except Exception:  # noqa: BLE001 — secrets absents ou exécution hors Streamlit
        pass
    return os.environ.get(env, defaut)


def config_smtp() -> dict:
    return {"host": _secret("smtp", "host", "DC_SMTP_HOST"), "port": int(_secret("smtp", "port", "DC_SMTP_PORT", 587)),
            "user": _secret("smtp", "user", "DC_SMTP_USER"), "password": _secret("smtp", "password", "DC_SMTP_PASSWORD"),
            "expediteur": _secret("smtp", "expediteur", "DC_SMTP_EXPEDITEUR")}


def jeton_telegram() -> str | None:
    return _secret("telegram", "bot_token", "DC_TELEGRAM_TOKEN")


def url_application() -> str:
    return _secret("dc", "url", "DC_URL", URL_DEFAUT)


def courriel_configure() -> bool:
    return bool(config_smtp()["host"])


def telegram_configure() -> bool:
    return bool(jeton_telegram())


def canaux_configures() -> dict[str, bool]:
    return {"Courriel": courriel_configure(), "Telegram": telegram_configure()}


def envoyer_courriel(destinataire: str, sujet: str, corps: str) -> Resultat:
    cfg = config_smtp()
    if not cfg["host"]:
        return Resultat("Canal non configuré", "Serveur d'envoi (SMTP) non déclaré dans les secrets.")
    if not destinataire:
        return Resultat("Échec", "Adresse de courriel absente de l'annuaire.")
    try:
        msg = MIMEText(corps, "plain", "utf-8")
        msg["Subject"] = sujet
        msg["From"] = cfg["expediteur"] or cfg["user"] or "datacenter@aer"
        msg["To"] = destinataire
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=DELAI_S) as s:
            s.starttls()
            if cfg["user"]:
                s.login(cfg["user"], cfg["password"] or "")
            s.send_message(msg)
        return Resultat("Envoyée")
    except Exception as e:  # noqa: BLE001 — une notification en échec ne doit jamais bloquer l'application
        return Resultat("Échec", f"{type(e).__name__} : {e}"[:300])


def envoyer_telegram(identifiant: str, texte: str) -> Resultat:
    jeton = jeton_telegram()
    if not jeton:
        return Resultat("Canal non configuré", "Jeton du bot Telegram non déclaré dans les secrets.")
    if not identifiant:
        return Resultat("Échec", "Identifiant Telegram absent de l'annuaire.")
    try:
        import requests
        r = requests.post(f"https://api.telegram.org/bot{jeton}/sendMessage",
                          json={"chat_id": str(identifiant).strip(), "text": texte[:4000]}, timeout=DELAI_S)
        if r.status_code == 200 and r.json().get("ok"):
            return Resultat("Envoyée")
        # le jeton figure dans l'adresse appelée : on ne recopie que la réponse de Telegram
        return Resultat("Échec", f"Telegram a répondu {r.status_code} : {r.text[:200]}")
    except Exception as e:  # noqa: BLE001
        return Resultat("Échec", f"{type(e).__name__}"[:300])


def envoyer(canal: str, adresse: str, sujet: str, corps: str) -> Resultat:
    """Point d'entrée unique (remplaçable dans les tests)."""
    if canal == "Courriel":
        return envoyer_courriel(adresse, sujet, corps)
    if canal == "Telegram":
        return envoyer_telegram(adresse, f"{sujet}\n\n{corps}")
    return Resultat("Échec", f"Canal inconnu : {canal}")


# ----------------------------------------------------------------------------- rédaction des messages
def message_alerte(a: dict, niveau: int, libelle_niveau: str, minutes_ecoulees: float, equipement: str | None) -> tuple[str, str]:
    """Sujet et corps d'une notification d'alerte. Aucune donnée sensible (adresse IP, compte) n'y figure :
    seulement le titre de l'alerte, l'équipement et les horodatages."""
    sev = str(a["severite"]).upper()
    sujet = f"[Data Center AER] {sev} — {a['titre']}"[:200]
    lignes = [f"Alerte n° {a['id']} — {a['severite']}",
              f"Objet : {a['titre']}",
              f"Équipement : {equipement or '—'} · Système : {a.get('systeme') or '—'}",
              f"Émise le {a['emise']:%d/%m/%Y à %H:%M} (heure de Douala)"]
    if a.get("description"):
        lignes.append(f"Détail : {a['description']}")
    if minutes_ecoulees >= 1:
        lignes.append(f"ESCALADE — {libelle_niveau} : alerte non acquittée depuis {int(minutes_ecoulees)} min.")
    else:
        lignes.append(f"Destinataires : {libelle_niveau}.")
    lignes += ["", f"Acquitter l'alerte : {url_application()}", "Message automatique du module Data Center FM800."]
    return sujet, "\n".join(lignes)
