import re

import pandas as pd
import plotly.express as px
import streamlit as st

from utils.data import NAVY, RED, GREEN, AMBER
from utils.loader import get_data
from utils.storage import mettre_a_jour, session_ou_stockage
from utils.ui import PAGE_ICON, inject_base_style, section_title, plotly_base_layout, kpi_row, render_sidebar_footer, style_map

from utils.parametres import memoriser, valeur
st.set_page_config(page_title="Supervision des centrales — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()
data = get_data()

COLS = ["Centrale", "Date", "Production (kWh)", "Consommation (kWh)", "Alarmes"]


def _vide() -> pd.DataFrame:
    return pd.DataFrame({"Centrale": pd.Series(dtype="string"), "Date": pd.Series(dtype="datetime64[ns]"),
                         "Production (kWh)": pd.Series(dtype="float"), "Consommation (kWh)": pd.Series(dtype="float"),
                         "Alarmes": pd.Series(dtype="float")})


def _devine(cols, motifs):
    for c in cols:
        if re.search(motifs, str(c), flags=re.I):
            return c
    return None


st.title("📡 Supervision des centrales solaires")
st.caption("Importez les exports de la plateforme de supervision (FusionSolar ou autre, un ou plusieurs fichiers "
           "CSV/Excel). L'application les ramène à une mesure par centrale et par jour, détecte les centrales qui "
           "ne remontent plus de données et calcule leur disponibilité. Les mesures sont enregistrées.")

mes = session_ou_stockage("supervision_mesures", _vide)

with st.expander("📥 Importer des exports", expanded=mes.empty):
    fichiers = st.file_uploader("Exports (CSV ou XLSX)", type=["csv", "xlsx"], accept_multiple_files=True,
                                key="sup_files")
    if fichiers:
        apercu = fichiers[0]
        brut = pd.read_csv(apercu, sep=None, engine="python") if apercu.name.lower().endswith(".csv") \
            else pd.read_excel(apercu)
        apercu.seek(0)
        cols = ["(absente)"] + list(brut.columns)
        st.caption(f"Colonnes détectées dans « {apercu.name} » (la même correspondance s'applique à tous les fichiers) :")
        c1, c2, c3, c4, c5 = st.columns(5)
        def choix(col, lib, motif):
            g = _devine(brut.columns, motif)
            return col.selectbox(lib, cols, index=cols.index(g) if g in cols else 0, key=f"sup_map_{lib}")
        m_site = choix(c1, "Centrale", r"station|plant|site|centrale|nom")
        m_date = choix(c2, "Date / heure", r"time|date|heure|period")
        m_prod = choix(c3, "Production", r"yield|production|pv|generation|énergie produite|energy")
        m_cons = choix(c4, "Consommation", r"consum|consommation|load|charge")
        m_alar = choix(c5, "Alarmes / sévérité", r"alarm|sever|sévér|fault|défaut")
        st.dataframe(brut.head(5), width="stretch", hide_index=True)
        if st.button("Intégrer ces fichiers", type="primary", disabled=(m_date == "(absente)" or m_prod == "(absente)")):
            lots = []
            for f in fichiers:
                d = pd.read_csv(f, sep=None, engine="python") if f.name.lower().endswith(".csv") else pd.read_excel(f)
                out = pd.DataFrame()
                out["Centrale"] = d[m_site].astype(str) if m_site != "(absente)" else re.sub(r"\.[^.]+$", "", f.name)
                out["Date"] = pd.to_datetime(d[m_date], errors="coerce", dayfirst=True).dt.normalize()
                out["Production (kWh)"] = pd.to_numeric(d[m_prod], errors="coerce")
                out["Consommation (kWh)"] = pd.to_numeric(d[m_cons], errors="coerce") if m_cons != "(absente)" else float("nan")
                out["Alarmes"] = d[m_alar].notna().astype(float) if m_alar != "(absente)" else 0.0
                lots.append(out.dropna(subset=["Date"]))
            neuf = pd.concat(lots, ignore_index=True)
            jour = neuf.groupby(["Centrale", "Date"], as_index=False).agg(
                **{"Production (kWh)": ("Production (kWh)", "sum"), "Consommation (kWh)": ("Consommation (kWh)", "sum"),
                   "Alarmes": ("Alarmes", "sum")})
            tout = pd.concat([mes, jour], ignore_index=True).drop_duplicates(["Centrale", "Date"], keep="last")
            mettre_a_jour("supervision_mesures", tout.sort_values(["Centrale", "Date"]).reset_index(drop=True),
                          f"import de {len(fichiers)} fichier(s), {len(jour)} mesure(s) journalière(s)")
            st.success(f"{len(jour)} mesure(s) journalière(s) intégrée(s) pour {jour['Centrale'].nunique()} centrale(s).")
            st.rerun()
    if not mes.empty and st.button("🗑️ Vider les mesures enregistrées"):
        mettre_a_jour("supervision_mesures", _vide(), "mesures vidées")
        st.rerun()

if mes.empty:
    st.info("Aucune mesure enregistrée pour l'instant. La connexion directe à l'API FusionSolar (Northbound) pourra "
            "remplacer l'import manuel dès que l'AER disposera d'un compte API Huawei.")
    render_sidebar_footer(data.generated_on if data else "")
    st.stop()

mes = mes.copy()
mes["Date"] = pd.to_datetime(mes["Date"])
c1, c2, c3 = st.columns(3)
dmin, dmax = mes["Date"].min().date(), mes["Date"].max().date()
periode = c1.date_input("Période analysée", (dmin, dmax), min_value=dmin, max_value=dmax, format="DD/MM/YYYY")
_modes = ["Dernière date des données", "Aujourd'hui"]
ref_mode = c2.radio("Date de référence pour le silence", _modes, horizontal=True,
                    index=_modes.index(valeur("supervision", "ref_mode", _modes[0])) if valeur("supervision", "ref_mode", _modes[0]) in _modes else 0)
seuil = c3.number_input("Centrale silencieuse au-delà de (jours sans données)", 1, 90, int(valeur("supervision", "seuil", 2)))
memoriser("supervision", "ref_mode", ref_mode)
memoriser("supervision", "seuil", int(seuil))
d0, d1 = (pd.Timestamp(periode[0]), pd.Timestamp(periode[1])) if isinstance(periode, tuple) and len(periode) == 2 \
    else (pd.Timestamp(dmin), pd.Timestamp(dmax))
v = mes[(mes["Date"] >= d0) & (mes["Date"] <= d1)]
ref = pd.Timestamp(dmax) if ref_mode.startswith("Dernière") else pd.Timestamp.today().normalize()
nb_jours = (d1 - d0).days + 1

synth = v.groupby("Centrale").agg(**{"Dernière donnée": ("Date", "max"), "Jours avec production": ("Production (kWh)", lambda s: int((s > 0).sum())),
                                     "Production (kWh)": ("Production (kWh)", "sum"), "Consommation (kWh)": ("Consommation (kWh)", "sum"),
                                     "Alarmes": ("Alarmes", "sum")}).reset_index()
toutes = pd.DataFrame({"Centrale": mes["Centrale"].unique()})
synth = toutes.merge(synth, on="Centrale", how="left")
synth["Dernière donnée"] = synth["Centrale"].map(mes.groupby("Centrale")["Date"].max())
synth["Jours sans données"] = (ref - synth["Dernière donnée"]).dt.days
synth["Disponibilité (%)"] = (synth["Jours avec production"].fillna(0) / nb_jours * 100).round(1)
synth["État"] = synth.apply(lambda r: "Silencieuse" if r["Jours sans données"] > seuil else
                            ("Dégradée" if r["Disponibilité (%)"] < 90 else "Opérationnelle"), axis=1)

n = len(synth)
kpi_row([
    ("Centrales suivies", str(n), None),
    ("Opérationnelles", str(int((synth["État"] == "Opérationnelle").sum())), None),
    ("Dégradées (dispo. < 90 %)", str(int((synth["État"] == "Dégradée").sum())), None),
    ("Silencieuses", str(int((synth["État"] == "Silencieuse").sum())), None),
    ("Production sur la période", f"{v['Production (kWh)'].sum():,.0f} kWh".replace(",", " "), None),
    ("Disponibilité moyenne", f"{synth['Disponibilité (%)'].mean():.1f} %", None),
])

section_title("ÉTAT DES CENTRALES")
couleurs = {"Opérationnelle": f"color:{GREEN};font-weight:600", "Dégradée": f"color:{AMBER};font-weight:600",
            "Silencieuse": f"color:{RED};font-weight:600"}
synth = synth.sort_values(["État", "Disponibilité (%)"], ascending=[False, True])
st.dataframe(style_map(synth.style, lambda x: couleurs.get(x, ""), subset=["État"]), width="stretch", hide_index=True,
             column_config={"Dernière donnée": st.column_config.DateColumn(format="DD/MM/YYYY")})

section_title("PRODUCTION JOURNALIÈRE")
choix = st.multiselect("Centrales", sorted(v["Centrale"].unique()), default=sorted(v["Centrale"].unique())[:5])
if choix:
    fig = px.line(v[v["Centrale"].isin(choix)], x="Date", y="Production (kWh)", color="Centrale",
                  title="Production journalière (kWh)")
    st.plotly_chart(plotly_base_layout(fig, height=380), width="stretch")
st.download_button("⬇️ Exporter l'état des centrales (CSV)", synth.to_csv(index=False).encode("utf-8"),
                   "etat_centrales.csv", "text/csv")

render_sidebar_footer(data.generated_on if data else "")
