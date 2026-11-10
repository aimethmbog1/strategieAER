import io

import pandas as pd
import streamlit as st

from utils.auth import journaliser, peut_voir_paie, require_role
from utils.storage import (
    REGISTRES, charger, charger_fichiers, etat_registres, lire_journal, moteur_description, moteur_ephemere,
)
from utils.ui import PAGE_ICON, inject_base_style, kpi_row, section_title

st.set_page_config(page_title="Explorateur de la base — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()
require_role({"admin", "direction", "sdmse"}, "l'explorateur de la base")

REGISTRES_PAIE = {"paie_registre", "recr_profils"}  # données nominatives de rémunération
REGISTRES_FICHIERS = {"classeur_principal", "compteurs_lots"}  # contenu = fichiers déposés

st.title("🗄️ Explorateur de la base")
st.caption("Consultation, en lecture seule, de tout ce que l'application a enregistré dans la base de données : "
           "registres saisis, fichiers déposés et journal des actions. Les modifications se font dans les pages "
           "concernées.")

# ----------------------------------------------------------------------------- état général
etat = etat_registres()
if not peut_voir_paie():
    etat = etat[~etat["Nom technique"].isin(REGISTRES_PAIE)]
remplis = etat[etat["Dernière mise à jour"] != "—"]
kpi_row([
    ("Moteur", "Neon / PostgreSQL" if "postgres" in moteur_description() else "SQLite local", None),
    ("Registres enregistrés", f"{len(remplis)} / {len(etat)}", None),
    ("Volume total", f"{etat['Taille (Ko)'].sum():,.1f} Ko".replace(",", " ").replace(".", ","), None),
    ("Dernière écriture", (remplis["Dernière mise à jour"].max()[:16].replace("T", " ") if len(remplis) else "—"), None),
])
if moteur_ephemere():
    st.warning("⚠️ Stockage temporaire : sans base externe déclarée, ces données sont effacées au redémarrage.")

onglets = st.tabs(["📚 Registres", "📄 Fichiers déposés", "🕓 Journal des actions"])


def _filtrer(df: pd.DataFrame, cle: str) -> pd.DataFrame:
    """Recherche plein texte + choix des colonnes."""
    c1, c2 = st.columns([2, 3])
    q = c1.text_input("Rechercher (toutes colonnes)", key=f"q_{cle}", placeholder="ex. Mayo-Banyo, 2026, Toyota…")
    cols = c2.multiselect("Colonnes affichées", list(df.columns), default=list(df.columns), key=f"c_{cle}")
    out = df[cols] if cols else df
    if q:
        masque = out.astype(str).apply(lambda s: s.str.contains(q, case=False, regex=False, na=False)).any(axis=1)
        out = out[masque]
    return out


def _exports(df: pd.DataFrame, base: str, cle: str):
    c1, c2, _ = st.columns([1, 1, 3])
    c1.download_button("⬇️ CSV", df.to_csv(index=False, sep=";").encode("utf-8-sig"), f"{base}.csv", "text/csv",
                       key=f"csv_{cle}")
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    c2.download_button("⬇️ Excel", buf.getvalue(), f"{base}.xlsx", key=f"xlsx_{cle}",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ----------------------------------------------------------------------------- 1. registres
with onglets[0]:
    section_title("État des registres")
    st.dataframe(etat, width="stretch", hide_index=True)

    tabulaires = remplis[~remplis["Nom technique"].isin(REGISTRES_FICHIERS)]
    if tabulaires.empty:
        st.info("Aucun registre de données saisies n'est encore enregistré.")
    else:
        section_title("Contenu d'un registre")
        libelles = dict(zip(tabulaires["Nom technique"], tabulaires["Registre"]))
        nom = st.selectbox("Registre", list(libelles), format_func=lambda n: libelles[n], key="reg_choix")
        df = charger(nom)
        if df is None or df.empty:
            st.info("Ce registre est vide.")
        else:
            st.caption(f"{len(df)} ligne(s) · {len(df.columns)} colonne(s) · mis à jour le "
                       f"{tabulaires.set_index('Nom technique').at[nom, 'Dernière mise à jour'][:16].replace('T', ' ')}")
            vue = _filtrer(df, nom)
            st.dataframe(vue, width="stretch", hide_index=True, height=min(80 + 35 * len(vue), 560))
            st.caption(f"{len(vue)} ligne(s) affichée(s)")
            _exports(vue, nom, nom)
            if nom in REGISTRES_PAIE:
                journaliser("Consultation", f"Explorateur — {REGISTRES.get(nom, nom)}")

# ----------------------------------------------------------------------------- 2. fichiers
with onglets[1]:
    section_title("Fichiers déposés et conservés dans la base")
    choix = {"compteurs_lots": "Lots de compteurs (Statistiques compteurs)",
             "classeur_principal": "Classeur de données principal (parc solaire, équipes)"}
    reg = st.radio("Registre de fichiers", list(choix), format_func=choix.get, horizontal=True, key="fic_reg")
    fichiers = charger_fichiers(reg)
    if not fichiers:
        st.info("Aucun fichier enregistré dans ce registre pour l'instant.")
    else:
        liste = pd.DataFrame([{"Fichier": f["fichier"], "Taille (Ko)": round(len(f["contenu"]) / 1024, 1),
                               "Enregistré le": f["maj"][:16].replace("T", " ")} for f in fichiers])
        st.dataframe(liste, width="stretch", hide_index=True)
        nom_f = st.selectbox("Aperçu du fichier", [f["fichier"] for f in fichiers], key="fic_choix")
        f = next(x for x in fichiers if x["fichier"] == nom_f)
        st.download_button(f"⬇️ Télécharger l'original ({nom_f})", f["contenu"], nom_f, key="fic_dl")
        try:
            if reg == "compteurs_lots":
                from utils.compteurs import lire_fichier_compteurs
                apercu = lire_fichier_compteurs(nom_f, f["contenu"])
            else:
                xls = pd.ExcelFile(io.BytesIO(f["contenu"]))
                feuille = st.selectbox("Feuille", xls.sheet_names, key="fic_feuille")
                apercu = pd.read_excel(xls, sheet_name=feuille)
            apercu = apercu.dropna(how="all").dropna(axis=1, how="all")
            apercu.columns = [str(c) for c in apercu.columns]
            st.caption(f"{len(apercu)} ligne(s) · {len(apercu.columns)} colonne(s)")
            vue = _filtrer(apercu, f"fic_{reg}")
            st.dataframe(vue, width="stretch", hide_index=True, height=min(80 + 35 * len(vue), 560))
            _exports(vue, nom_f.rsplit(".", 1)[0], f"fic_{reg}")
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Aperçu impossible pour ce fichier : {exc}")

# ----------------------------------------------------------------------------- 3. journal
with onglets[2]:
    section_title("Journal des actions")
    j = lire_journal(5000)
    if j.empty:
        st.info("Le journal est vide.")
    else:
        c1, c2 = st.columns(2)
        users = c1.multiselect("Utilisateur", sorted(j["Utilisateur"].dropna().unique()), key="j_users")
        act = c2.text_input("Action ou détail contient", key="j_act")
        v = j
        if users:
            v = v[v["Utilisateur"].isin(users)]
        if act:
            v = v[v["Action"].str.contains(act, case=False, na=False) | v["Détail"].str.contains(act, case=False, na=False)]
        st.dataframe(v, width="stretch", hide_index=True, height=min(80 + 35 * len(v), 560))
        st.caption(f"{len(v)} action(s) — les plus récentes en premier")
        _exports(v, "journal_actions", "journal")
