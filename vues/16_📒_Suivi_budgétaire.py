from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils.data import NAVY, BLUE, GOLD
from utils.loader import get_data
from utils.storage import enregistrer_si_change, session_ou_stockage
from utils.ui import PAGE_ICON, inject_base_style, section_title, plotly_base_layout, kpi_row, render_sidebar_footer

st.set_page_config(page_title="Suivi budgétaire — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()
data = get_data()

SEED = Path(__file__).resolve().parent.parent / "data" / "budget_sdmse_2027.csv"
MONTANTS = ["Montant prévu (FCFA)", "Engagé (FCFA)", "Payé (FCFA)"]


def _seed() -> pd.DataFrame:
    df = pd.read_csv(SEED, dtype=str).fillna("")
    df.insert(0, "Exercice", "2027")
    for c in MONTANTS:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df


def _fcfa(x) -> str:
    return f"{x:,.0f} F".replace(",", " ")


st.title("📒 Suivi budgétaire — exécution des activités")
st.caption("Prévisions, engagements et paiements par activité et par tâche, avec les indicateurs de performance. "
           "Le registre est initialisé avec le budget 2027 de la SDMSE (264 108 000 FCFA, 9 activités) ; "
           "les montants engagés, payés et les réalisations se saisissent au fil de l'exercice.")

base = session_ou_stockage("budget_register", _seed)

with st.expander("📥 Importer / ↺ réinitialiser"):
    c1, c2 = st.columns([2, 1])
    f = c1.file_uploader("Registre budgétaire (CSV/XLSX, mêmes colonnes que l'export)", type=["csv", "xlsx"],
                         key="budget_import")
    if f is not None and c1.button("Importer ce fichier"):
        imp = pd.read_csv(f) if f.name.lower().endswith(".csv") else pd.read_excel(f)
        manquantes = [c for c in base.columns if c not in imp.columns]
        if manquantes:
            st.error(f"Colonnes manquantes : {', '.join(manquantes)}")
        else:
            st.session_state["budget_register"] = imp[base.columns]
            st.session_state["budget_ver"] = st.session_state.get("budget_ver", 0) + 1
            enregistrer_si_change("budget_register", st.session_state["budget_register"])
            st.rerun()
    if c2.button("Revenir au budget 2027 initial"):
        st.session_state["budget_register"] = _seed()
        st.session_state["budget_ver"] = st.session_state.get("budget_ver", 0) + 1
        enregistrer_si_change("budget_register", st.session_state["budget_register"])
        st.rerun()

exercices = sorted(base["Exercice"].astype(str).unique())
c1, c2, c3 = st.columns(3)
f_ex = c1.selectbox("Exercice", exercices, index=len(exercices) - 1)
volets = sorted(base["Volet"].dropna().astype(str).unique())
f_vol = c2.multiselect("Volet", volets)
f_fi = c3.multiselect("Fonctionnement / Investissement", ["F", "I"])

section_title("REGISTRE BUDGÉTAIRE (saisie)")
cfg = {c: st.column_config.NumberColumn(min_value=0, step=1000, format="%d") for c in MONTANTS}
cfg["F/I"] = st.column_config.SelectboxColumn(options=["F", "I"])
edite = st.data_editor(base, column_config=cfg, num_rows="dynamic", width="stretch", hide_index=True, height=420,
                       key=f"budget_editor_{st.session_state.get('budget_ver', 0)}")
enregistrer_si_change("budget_register", edite)

v = edite[edite["Exercice"].astype(str) == f_ex].copy()
if f_vol:
    v = v[v["Volet"].isin(f_vol)]
if f_fi:
    v = v[v["F/I"].isin(f_fi)]
for c in MONTANTS:
    v[c] = pd.to_numeric(v[c], errors="coerce").fillna(0.0)

prevu, engage, paye = (v[c].sum() for c in MONTANTS)
kpi_row([
    ("Prévu", _fcfa(prevu), None),
    ("Engagé", _fcfa(engage), f"{engage / prevu:.1%} du prévu".replace(".", ",") if prevu else None),
    ("Payé", _fcfa(paye), f"{paye / prevu:.1%} du prévu".replace(".", ",") if prevu else None),
    ("Disponible (prévu − engagé)", _fcfa(prevu - engage), None),
    ("Tâches avec réalisation renseignée", f"{(v['Réalisé'].astype(str).str.strip() != '').sum()} / {len(v)}", None),
])

section_title("EXÉCUTION PAR ACTIVITÉ")
par_act = v.groupby("Activité", as_index=False)[MONTANTS].sum()
par_act["Taux d'engagement (%)"] = (par_act["Engagé (FCFA)"] / par_act["Montant prévu (FCFA)"] * 100).round(1)
par_act["Taux de paiement (%)"] = (par_act["Payé (FCFA)"] / par_act["Montant prévu (FCFA)"] * 100).round(1)
par_act = par_act.sort_values("Montant prévu (FCFA)", ascending=True)
fig = go.Figure()
for col, coul in zip(MONTANTS, [GOLD, BLUE, NAVY]):
    fig.add_bar(y=par_act["Activité"].str.slice(0, 60), x=par_act[col], name=col.replace(" (FCFA)", ""),
                orientation="h", marker_color=coul)
fig.update_layout(barmode="group", title="Prévu, engagé et payé par activité (FCFA)", xaxis_title=None)
st.plotly_chart(plotly_base_layout(fig, height=max(360, 70 * len(par_act) + 80)), width="stretch")
st.dataframe(par_act.sort_values("Montant prévu (FCFA)", ascending=False), width="stretch", hide_index=True,
             column_config={c: st.column_config.NumberColumn(format="%d") for c in MONTANTS})

section_title("INDICATEURS DE PERFORMANCE")
ind = v.drop_duplicates(subset=["Tâche"])[["Activité", "Tâche", "Indicateur", "Référence", "Cible", "Réalisé",
                                           "Source de vérification"]]
st.dataframe(ind, width="stretch", hide_index=True, height=360)
st.download_button("⬇️ Exporter le registre budgétaire (CSV)", edite.to_csv(index=False).encode("utf-8"),
                   "suivi_budgetaire_aer.csv", "text/csv")

render_sidebar_footer(data.generated_on if data else "")
