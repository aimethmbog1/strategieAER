import pandas as pd
import streamlit as st

from utils.auth import journaliser, peut_voir_paie
from utils.loader import get_data
from utils.plaidoyer import (
    AUDIENCES, REFERENCES_DEFAUT, SECTIONS, TEXTES_ANCIENS, TEXTES_DEFAUT, annexe_excel, controles, generer_pdf, indicateurs,
    remplir, valeurs_gabarit,
)
from utils.storage import enregistrer_si_change, session_ou_stockage
from utils.ui import PAGE_ICON, inject_base_style, section_title, render_sidebar_footer

from utils.parametres import memoriser, valeur
st.set_page_config(page_title="Dossier de plaidoyer — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()
data = get_data()
if data is None:
    st.stop()

st.title("🎯 Dossier de plaidoyer")
st.caption("Assemble un dossier institutionnel en français et en anglais à partir des chiffres de l'application. "
           "Chaque chiffre porte sa source, sa date et son statut ; les incohérences entre sources sont signalées "
           "avant la génération, pour qu'aucun document ne parte avec un chiffre contestable.")

# ----------------------------------------------------------- destinataire
c1, c2 = st.columns([1, 2])
_aud = list(AUDIENCES)
audience = c1.selectbox("Destinataire", _aud, index=_aud.index(valeur("plaidoyer", "audience", _aud[0]))
                        if valeur("plaidoyer", "audience", _aud[0]) in _aud else 0)
titre_def = {"Partenaires techniques et financiers": "Électrification rurale par centrales solaires — Cameroun"}.get(
    audience, "Électrification rurale par centrales solaires — bilan et perspectives")
titre_fr = c2.text_input("Titre (français)", valeur("plaidoyer", f"titre_fr_{audience}", titre_def))
titre_en = c2.text_input("Title (English)", valeur("plaidoyer", f"titre_en_{audience}",
                         "Rural electrification through solar mini-grids — Cameroon: results and outlook"))
memoriser("plaidoyer", "audience", audience)
memoriser("plaidoyer", f"titre_fr_{audience}", titre_fr)
memoriser("plaidoyer", f"titre_en_{audience}", titre_en)

# ----------------------------------------------------------- références validées
section_title("1. RÉFÉRENCES VALIDÉES (chiffres institutionnels)")
st.caption("Chiffres issus des rapports officiels, qui ne sont pas recalculables dans l'application. Mettez à jour la "
           "valeur, la date et le statut avant chaque dossier ; une ligne « À actualiser » est signalée.")


def _refs() -> pd.DataFrame:
    return pd.DataFrame([{"Indicateur": a, "Indicator": b, "Valeur": float(c), "Unité": d, "Source": e,
                          "Date": "2026", "Statut": "À actualiser"} for a, b, c, d, e in REFERENCES_DEFAUT])


refs_base = session_ou_stockage("plaidoyer_references", _refs)
# Ajoute les références par défaut apparues depuis le dernier enregistrement (sans toucher aux lignes existantes).
_manquantes = _refs()[~_refs()["Indicateur"].isin(refs_base["Indicateur"])]
if not _manquantes.empty:
    refs_base = pd.concat([refs_base, _manquantes], ignore_index=True)
    st.session_state["plaidoyer_references"] = refs_base
refs = st.data_editor(refs_base, num_rows="dynamic", width="stretch", hide_index=True, key="pl_refs",
                      column_config={"Valeur": st.column_config.NumberColumn(format="%.0f"),
                                     "Statut": st.column_config.SelectboxColumn(
                                         options=["Validé", "Calculé", "Provisoire", "À actualiser"], required=True)})
enregistrer_si_change("plaidoyer_references", refs)

# ----------------------------------------------------------- indicateurs
section_title("2. INDICATEURS RETENUS")
inclure_paie = False
if peut_voir_paie():
    inclure_paie = st.checkbox("Inclure les indicateurs de masse salariale (données de paie)",
                               value=bool(valeur("plaidoyer", "inclure_paie", False)),
                               help="Désactivé par défaut : la paie est une donnée sensible, à n'inclure que pour les "
                                    "destinataires concernés.")
memoriser("plaidoyer", "inclure_paie", bool(inclure_paie))
ind = indicateurs(data, inclure_paie, refs)
_exclus = set(valeur("plaidoyer", "indicateurs_exclus", []))  # on mémorise les exclusions : les nouveaux indicateurs restent inclus
retenus = st.multiselect("Indicateurs à faire figurer dans le dossier", ind["Indicateur"].tolist(),
                         default=[i for i in ind["Indicateur"].tolist() if i not in _exclus])
memoriser("plaidoyer", "indicateurs_exclus", sorted(set(ind["Indicateur"]) - set(retenus)))
ind = ind[ind["Indicateur"].isin(retenus)]
from utils.plaidoyer import _fmt
aff = ind.copy()
aff["Valeur"] = aff["Valeur"].map(lambda x: _fmt(x, 1 if isinstance(x, float) and not float(x).is_integer() else 0))
st.dataframe(aff, width="stretch", hide_index=True, height=min(80 + 35 * len(ind), 520))
avert = controles(ind)
if avert:
    st.warning("**Points de cohérence à lever avant diffusion :**\n\n" + "\n".join(f"- {a}" for a in avert))
else:
    st.success("Aucune incohérence détectée entre les sources retenues.")

# ----------------------------------------------------------- textes
section_title("3. TEXTES DU DOSSIER (FR / EN)")
st.caption("Les accolades sont remplacées par les chiffres ci-dessus. Principales : {sites}, {kwc}, {antennes}, "
           "{equipes}, {pourvus}, {requis}, {manques}, {budget}, {budget_f}, {budget_i}, {centrales_op}, "
           "{compteurs_installes}, {potentiel_menages}, {taux_comptage}, {compteurs_annee}, {compteurs_phases}, "
           "{dispo_dc}, {requetes}, {centrales_supervisees}, {annee}, {recettes_annee}, {recettes_comp}, "
           "{periode_comp}, {evol_recettes}, {cumul_recettes}, {kwh_client_debut}, {annee_debut}, {kwh_client_fin}. "
           "Remplacez les passages ⟨…⟩ par votre rédaction ; ils restent visibles dans le PDF tant qu'ils ne sont pas "
           "complétés. Chaque partie est rédigée pour occuper au moins une page du PDF.")


def _textes() -> pd.DataFrame:
    return pd.DataFrame([{"cle": k, "fr": TEXTES_DEFAUT[k][0], "en": TEXTES_DEFAUT[k][1]} for k, _, _ in SECTIONS])


tx = session_ou_stockage("plaidoyer_textes", _textes).copy()
# Mise à niveau : une section jamais modifiée (identique à l'ancien texte type) reçoit la version argumentée.
for _i, _r in tx.iterrows():
    if _r["cle"] in TEXTES_ANCIENS:
        for _j, _col in enumerate(("fr", "en")):
            if str(_r[_col]).strip() == TEXTES_ANCIENS[_r["cle"]][_j].strip():
                tx.at[_i, _col] = TEXTES_DEFAUT[_r["cle"]][_j]
if st.button("↺ Recharger les textes types argumentés", help="Remplace les cinq parties (FR et EN) par les textes "
             "types de l'application. Vos modifications actuelles seront perdues."):
    tx = _textes()
    for _cle, _, _ in SECTIONS:
        st.session_state.pop(f"pl_fr_{_cle}", None)
        st.session_state.pop(f"pl_en_{_cle}", None)
valeurs = valeurs_gabarit(ind)
valeurs_en = valeurs_gabarit(ind, en=True)
onglets = st.tabs([t for _, t, _ in SECTIONS])
for (cle, tfr, ten), ong in zip(SECTIONS, onglets):
    with ong:
        i = tx.index[tx["cle"] == cle][0]
        a, b = st.columns(2)
        tx.at[i, "fr"] = a.text_area(f"Français — {tfr}", tx.at[i, "fr"], height=480, key=f"pl_fr_{cle}")
        tx.at[i, "en"] = b.text_area(f"English — {ten}", tx.at[i, "en"], height=480, key=f"pl_en_{cle}")
        with st.expander("Aperçu avec les chiffres"):
            st.markdown(remplir(tx.at[i, "fr"], valeurs))
            st.markdown("---")
            st.markdown(remplir(tx.at[i, "en"], valeurs_en))
enregistrer_si_change("plaidoyer_textes", tx)
textes = {r["cle"]: (r["fr"], r["en"]) for _, r in tx.iterrows()}
incomplets = [t for (k, t, _) in SECTIONS if "⟨" in textes[k][0] or "⟨" in textes[k][1]]
if incomplets:
    st.info("Sections encore à compléter : " + ", ".join(incomplets))

# ----------------------------------------------------------- génération
section_title("4. GÉNÉRATION")
genere_le = pd.Timestamp.now().strftime("%d/%m/%Y")
c1, c2, c3 = st.columns(3)
if c1.button("📄 Générer le dossier en français", type="primary", width="stretch"):
    with st.spinner("Mise en page…"):
        st.session_state["pl_pdf_fr"] = generer_pdf("FR", audience, titre_fr, textes, ind, avert, genere_le, data)
    journaliser("Génération du dossier de plaidoyer (FR)", audience)
if c2.button("📄 Generate the English file", type="primary", width="stretch"):
    with st.spinner("Layout…"):
        st.session_state["pl_pdf_en"] = generer_pdf("EN", audience, titre_en, textes, ind, avert, genere_le, data)
    journaliser("Génération du dossier de plaidoyer (EN)", audience)
c3.download_button("📊 Annexe chiffrée (Excel)", annexe_excel(ind, avert), "annexe_indicateurs_aer.xlsx",
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
if st.session_state.get("pl_pdf_fr"):
    c1.download_button("⬇️ Télécharger le PDF (FR)", st.session_state["pl_pdf_fr"], "dossier_plaidoyer_AER_FR.pdf",
                       "application/pdf", width="stretch")
if st.session_state.get("pl_pdf_en"):
    c2.download_button("⬇️ Download the PDF (EN)", st.session_state["pl_pdf_en"], "advocacy_file_AER_EN.pdf",
                       "application/pdf", width="stretch")
st.caption("Conseil : faites relire le dossier par la Direction et levez les points de cohérence signalés avant tout "
           "envoi. Les traductions anglaises proposées par défaut sont à faire valider.")

render_sidebar_footer(data.generated_on)
