import re

import pandas as pd
import plotly.express as px
import streamlit as st

from utils.data import NAVY, GOLD
from utils.loader import get_data
from utils.storage import mettre_a_jour, session_ou_stockage
from utils.ui import PAGE_ICON, inject_base_style, section_title, plotly_base_layout, kpi_row, render_sidebar_footer, gauge_indicator

st.set_page_config(page_title="Recettes et abonnés — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()
data = get_data()


def _vide() -> pd.DataFrame:
    return pd.DataFrame({"Date": pd.Series(dtype="datetime64[ns]"), "Compteur": pd.Series(dtype="string"),
                         "Montant (FCFA)": pd.Series(dtype="float"), "Énergie (kWh)": pd.Series(dtype="float"),
                         "Localité": pd.Series(dtype="string")})


def _devine(cols, motif):
    return next((c for c in cols if re.search(motif, str(c), flags=re.I)), None)


def _fcfa(x):
    return f"{x:,.0f} F".replace(",", " ")


st.title("💵 Recettes et abonnés")
st.caption("Importez les états de vente (système Holley ou future application de vente de l'AER). L'application "
           "calcule les recettes, l'énergie vendue, les compteurs actifs et le taux de réalisation par rapport au "
           "potentiel — indicateurs au cœur des échanges avec les organes de contrôle.")

ventes = session_ou_stockage("ventes_register", _vide)

with st.expander("📥 Importer des états de vente", expanded=ventes.empty):
    fichiers = st.file_uploader("États de vente (CSV/XLSX/XLS)", type=["csv", "xlsx", "xls"], accept_multiple_files=True,
                                key="ventes_files")
    if fichiers:
        f0 = fichiers[0]
        brut = pd.read_csv(f0, sep=None, engine="python") if f0.name.lower().endswith(".csv") else pd.read_excel(f0)
        f0.seek(0)
        cols = ["(absente)"] + list(brut.columns)
        c = st.columns(5)
        def choix(col, lib, motif):
            g = _devine(brut.columns, motif)
            return col.selectbox(lib, cols, index=cols.index(g) if g in cols else 0, key=f"v_map_{lib}")
        m_date = choix(c[0], "Date de vente", r"date|time|heure")
        m_cpt = choix(c[1], "N° de compteur", r"meter|compteur|n°|numero|number")
        m_mnt = choix(c[2], "Montant (FCFA)", r"amount|montant|money|fcfa|prix|total")
        m_kwh = choix(c[3], "Énergie (kWh)", r"kwh|energy|énergie|unit")
        m_loc = choix(c[4], "Localité", r"address|adresse|localit|site|village")
        st.dataframe(brut.head(5), width="stretch", hide_index=True)
        if st.button("Intégrer ces états", type="primary", disabled="(absente)" in (m_date, m_cpt, m_mnt)):
            lots = []
            for f in fichiers:
                d = pd.read_csv(f, sep=None, engine="python") if f.name.lower().endswith(".csv") else pd.read_excel(f)
                lots.append(pd.DataFrame({
                    "Date": pd.to_datetime(d[m_date], errors="coerce", dayfirst=True),
                    "Compteur": d[m_cpt].astype(str).str.strip(),
                    "Montant (FCFA)": pd.to_numeric(d[m_mnt], errors="coerce"),
                    "Énergie (kWh)": pd.to_numeric(d[m_kwh], errors="coerce") if m_kwh != "(absente)" else float("nan"),
                    "Localité": d[m_loc].astype(str).str.strip().str.title() if m_loc != "(absente)" else "",
                }).dropna(subset=["Date", "Montant (FCFA)"]))
            neuf = pd.concat(lots, ignore_index=True)
            tout = pd.concat([ventes, neuf], ignore_index=True).drop_duplicates(keep="first")
            mettre_a_jour("ventes_register", tout.reset_index(drop=True), f"import de {len(neuf)} vente(s)")
            st.success(f"{len(neuf)} vente(s) intégrée(s) ({len(tout) - len(ventes)} nouvelle(s) après dédoublonnage).")
            st.rerun()
    if not ventes.empty and st.button("🗑️ Vider les ventes enregistrées"):
        mettre_a_jour("ventes_register", _vide(), "ventes vidées")
        st.rerun()

section_title("RÉFÉRENCES POUR LES TAUX")
c1, c2, c3 = st.columns(3)
parc = c1.number_input("Compteurs installés (parc de référence)", 0, 1_000_000, 8600, step=100,
                       help="Valeur validée 2026 : 8 600 (Phases I à III) — à actualiser")
potentiel = c2.number_input("Potentiel de ménages desservables", 0, 10_000_000, 59516, step=100,
                            help="Valeur validée : 59 516 — à actualiser")
fenetre = c3.number_input("Compteur actif = au moins un achat dans les N derniers jours", 7, 365, 90)

if ventes.empty:
    st.info("Aucune vente enregistrée : importez un état de vente pour calculer les indicateurs.")
    render_sidebar_footer(data.generated_on if data else "")
    st.stop()

v = ventes.copy()
v["Date"] = pd.to_datetime(v["Date"])
dmin, dmax = v["Date"].min().date(), v["Date"].max().date()
per = st.date_input("Période", (dmin, dmax), min_value=dmin, max_value=dmax, format="DD/MM/YYYY")
d0, d1 = (pd.Timestamp(per[0]), pd.Timestamp(per[1]) + pd.Timedelta(days=1)) if isinstance(per, tuple) and len(per) == 2 \
    else (pd.Timestamp(dmin), pd.Timestamp(dmax) + pd.Timedelta(days=1))
p = v[(v["Date"] >= d0) & (v["Date"] < d1)]
actifs = v[(v["Date"] > d1 - pd.Timedelta(days=int(fenetre))) & (v["Date"] < d1)]["Compteur"].nunique()
acheteurs = p["Compteur"].nunique()

kpi_row([
    ("Recettes sur la période", _fcfa(p["Montant (FCFA)"].sum()), None),
    ("Énergie vendue", f"{p['Énergie (kWh)'].sum():,.0f} kWh".replace(",", " ") if p["Énergie (kWh)"].notna().any() else "—", None),
    ("Transactions", f"{len(p):,}".replace(",", " "), None),
    ("Compteurs acheteurs (période)", f"{acheteurs:,}".replace(",", " "), None),
    (f"Compteurs actifs ({fenetre} j)", f"{actifs:,}".replace(",", " "), None),
    ("Panier moyen", _fcfa(p["Montant (FCFA)"].mean()) if len(p) else "—", None),
])
g1, g2 = st.columns(2)
with g1:
    st.plotly_chart(gauge_indicator(actifs / parc * 100 if parc else 0, f"Taux d'activité du parc ({fenetre} j)",
                                    low_threshold=50, high_threshold=80), width="stretch")
with g2:
    st.plotly_chart(gauge_indicator(actifs / potentiel * 100 if potentiel else 0,
                                    "Taux de réalisation (compteurs actifs / potentiel)", low_threshold=20,
                                    high_threshold=50), width="stretch")
st.caption("Taux de réalisation = compteurs actifs / potentiel de ménages. Les seuils de couleur sont indicatifs.")

section_title("RECETTES MENSUELLES")
mens = p.groupby(p["Date"].dt.to_period("M").dt.to_timestamp()).agg(
    **{"Recettes (FCFA)": ("Montant (FCFA)", "sum"), "Compteurs acheteurs": ("Compteur", "nunique")}).reset_index()
fig = px.bar(mens, x="Date", y="Recettes (FCFA)", color_discrete_sequence=[NAVY], title="Recettes par mois (FCFA)")
fig.update_xaxes(dtick="M1", tickformat="%m/%Y")
st.plotly_chart(plotly_base_layout(fig, height=360, legend=False), width="stretch")

if p["Localité"].astype(str).str.strip().ne("").any():
    section_title("PAR LOCALITÉ")
    loc = p.groupby("Localité").agg(**{"Recettes (FCFA)": ("Montant (FCFA)", "sum"), "Compteurs": ("Compteur", "nunique"),
                                       "Transactions": ("Compteur", "size")}).reset_index()
    loc["Recette par compteur (FCFA)"] = (loc["Recettes (FCFA)"] / loc["Compteurs"]).round(0)
    st.dataframe(loc.sort_values("Recettes (FCFA)", ascending=False), width="stretch", hide_index=True,
                 column_config={c: st.column_config.NumberColumn(format="%d") for c in ("Recettes (FCFA)", "Recette par compteur (FCFA)")})

render_sidebar_footer(data.generated_on if data else "")
