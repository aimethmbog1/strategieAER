from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from utils.data import NAVY, GOLD, GREY, GREEN, RED
from utils.loader import get_data
from utils.recharges import (
    COLONNES_BASE, MOIS_FR, MOIS_LONGS, controles_qualite, enrichir, lire_classeur_recharges, mois_complets,
)
from utils.storage import mettre_a_jour, session_ou_stockage
from utils.ui import (
    PAGE_ICON, BarreChargement, inject_base_style, kpi_row, plotly_base_layout, render_sidebar_footer,
    section_title,
)

st.set_page_config(page_title="Recharges Data Center — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()
data = get_data()


def _fcfa(x) -> str:
    return "—" if pd.isna(x) else f"{x:,.0f} F".replace(",", " ")


def _n(x) -> str:
    return "—" if pd.isna(x) else f"{x:,.0f}".replace(",", " ")


def _mf(x) -> str:
    """Montant en millions de FCFA, format français (ex. 476,45) — l'unité est dans le libellé."""
    return "—" if pd.isna(x) else f"{x / 1e6:,.2f}".replace(",", " ").replace(".", ",")


def _aff(fig, **kw):
    """Mise en forme commune + séparateurs français (virgule décimale, espace des milliers)."""
    fig = plotly_base_layout(fig, **kw)
    fig.update_layout(separators=", ")
    return fig


def _pct(x) -> str | None:
    return None if x is None or pd.isna(x) else f"{x:+.1f} %".replace(".", ",")


st.title("🔋 Recharges Data Center")
st.caption("Recettes des recharges prépayées des abonnés enregistrées par le Data Center (Meter Data System), "
           "consolidées par mois depuis 2021 à partir du classeur « Suivi des recharges ».")

# ----------------------------------------------------------------------------- données
registre = session_ou_stockage("recharges_datacenter", lambda: pd.DataFrame(columns=COLONNES_BASE))

with st.sidebar:
    st.markdown("### 🔋 Classeur des recharges")
    fichier = st.file_uploader("Suivi_Recharges_DataCenter.xlsx", type=["xlsx"], key="recharges_file",
                               help="Classeur contenant l'onglet « Recap_Mensuel » (ou « Saisie_Journaliere »).")

if fichier is not None:
    contenu = fichier.getvalue()
    signature = (fichier.name, len(contenu))
    try:
        if st.session_state.get("_recharges_signature") != signature:
            with BarreChargement("Lecture du classeur des recharges…", total=2) as barre:
                barre.etape("Lecture des onglets")
                lu = lire_classeur_recharges(contenu)
                barre.etape("Consolidation mensuelle")
            mettre_a_jour("recharges_datacenter", lu[COLONNES_BASE], f"{fichier.name} : {len(lu)} mois")
            st.session_state["_recharges_signature"] = signature
            st.toast(f"{len(lu)} mois chargés depuis {fichier.name}", icon="✅")
        registre = st.session_state["recharges_datacenter"]
    except Exception as exc:  # noqa: BLE001
        st.error(f"Impossible de lire ce classeur : {exc}")

# Données intégrées à l'application : utilisées tant qu'aucun classeur plus récent n'a été déposé.
FICHIER_INTEGRE = Path(__file__).resolve().parent.parent / "data" / "recharges_datacenter.xlsx"
source = st.session_state.get("_recharges_source", "données enregistrées dans l'application")
if (registre is None or registre.empty) and fichier is None and FICHIER_INTEGRE.exists():
    with BarreChargement("Chargement des données intégrées…", total=1) as barre:
        registre = lire_classeur_recharges(FICHIER_INTEGRE.read_bytes())[COLONNES_BASE]
        barre.etape("Données prêtes")
    st.session_state["recharges_datacenter"] = registre
    source = "données intégrées à l'application"
elif fichier is not None:
    source = f"classeur déposé : {fichier.name}"
st.session_state["_recharges_source"] = source

if registre is None or registre.empty:
    st.info("Aucune donnée de recharge pour l'instant. Dépose le classeur **Suivi_Recharges_DataCenter.xlsx** "
            "dans la barre latérale : il sera conservé pour les prochaines visites si le stockage durable est "
            "configuré.")
    render_sidebar_footer(data.generated_on if data else "")
    st.stop()

d_tout = enrichir(registre)
st.sidebar.caption(f"Source : **{source}** — {len(d_tout)} mois, "
                   f"{d_tout['mois'].min():%m/%Y} à {d_tout['mois'].max():%m/%Y}. Dépose un classeur plus récent "
                   "pour mettre à jour.")
aujourd_hui = pd.Timestamp.today().normalize()
mois_courant = aujourd_hui.to_period("M")

annees = sorted(d_tout["annee"].unique())
with st.sidebar:
    choix = st.multiselect("Années affichées", annees, default=annees, key="recharges_annees")
d = d_tout[d_tout["annee"].isin(choix or annees)]
d_complets = mois_complets(d, aujourd_hui)

# ----------------------------------------------------------------------------- KPI
annee_n = int(d_tout["annee"].max())
dernier_mois_complet = mois_complets(d_tout, aujourd_hui)["mois"].max()
m_max = dernier_mois_complet.month if (pd.notna(dernier_mois_complet) and dernier_mois_complet.year == annee_n) else 12
cumul_n = d_tout[(d_tout["annee"] == annee_n)]["recettes"].sum()
cumul_n_comp = d_tout[(d_tout["annee"] == annee_n) & (d_tout["mois_num"] <= m_max)]["recettes"].sum()
cumul_n1_comp = d_tout[(d_tout["annee"] == annee_n - 1) & (d_tout["mois_num"] <= m_max)]["recettes"].sum()
evol = (cumul_n_comp / cumul_n1_comp - 1) * 100 if cumul_n1_comp else None

kpi_row([
    (f"Recettes {annee_n} (M FCFA)", _mf(cumul_n), None),
    (f"Jan–{MOIS_FR[m_max - 1].lower()} {annee_n} (M FCFA)", _mf(cumul_n_comp), _pct(evol)),
    ("Cumul total (M FCFA)", _mf(d_tout["recettes"].sum()), None),
    ("Énergie vendue", f"{d['energie_kwh'].sum() / 1e6:,.2f} GWh".replace(".", ","), None),
    ("Moyenne/mois (M FCFA)", _mf(d_complets["recettes"].mean()), None),
])
st.caption(f"Recettes {annee_n} à date : {_fcfa(cumul_n)}. Évolution calculée à période égale "
           f"(janvier à {MOIS_LONGS[m_max - 1]}) par rapport à {annee_n - 1}, mois en cours exclu. Prix moyen observé : "
           f"{d_complets['prix_kwh'].median():.0f} FCFA/kWh.")

alertes = controles_qualite(d_tout, aujourd_hui)
if not alertes.empty:
    st.warning(f"⚠️ {len(alertes)} point(s) à vérifier dans le classeur source — voir l'onglet « Qualité des données ».")

onglets = st.tabs(["📈 Évolution mensuelle", "📊 Comparaison annuelle", "👥 Clients et consommation",
                   "🔍 Qualité des données", "📋 Données"])

# ----------------------------------------------------------------------------- 1. évolution
with onglets[0]:
    section_title("Recettes mensuelles et tendance sur 12 mois")
    serie = d.set_index("mois")["recettes"]
    tendance = d_tout.set_index("mois")["recettes"].rolling(12, min_periods=12).mean().reindex(serie.index)
    couleurs = [GREY if m.to_period("M") == mois_courant else NAVY for m in serie.index]
    fig = go.Figure()
    fig.add_bar(x=serie.index, y=serie.values, name="Recettes du mois", marker_color=couleurs,
                hovertemplate="%{x|%b %Y}<br>%{y:,.0f} FCFA<extra></extra>")
    fig.add_scatter(x=tendance.index, y=tendance.values, name="Moyenne mobile 12 mois", mode="lines",
                    line=dict(color=GOLD, width=3), hovertemplate="%{x|%b %Y}<br>%{y:,.0f} FCFA<extra></extra>")
    fig.update_yaxes(title="FCFA", tickformat=",.0f")
    st.plotly_chart(_aff(fig, height=420), width="stretch")
    st.caption("Barre grise : mois en cours, incomplet.")

    section_title("Recettes cumulées depuis 2021")
    cum = d_tout.set_index("mois")["recettes"].cumsum()
    fig = px.area(x=cum.index, y=cum.values, labels={"x": "", "y": "FCFA"}, color_discrete_sequence=[NAVY])
    fig.update_yaxes(tickformat=",.0f")
    st.plotly_chart(_aff(fig, height=320, legend=False), width="stretch")

# ----------------------------------------------------------------------------- 2. annuel
with onglets[1]:
    par_an = d.groupby("annee").agg(recettes=("recettes", "sum"), mois=("mois", "count"),
                                    energie=("energie_kwh", "sum")).reset_index()
    par_an["Statut"] = par_an.apply(lambda r: "Année en cours" if r["annee"] == aujourd_hui.year
                                    else ("Incomplète" if r["mois"] < 12 else "Complète"), axis=1)
    col1, col2 = st.columns(2)
    with col1:
        section_title("Recettes par année")
        fig = px.bar(par_an, x="annee", y="recettes", color="Statut", text="recettes",
                     color_discrete_map={"Complète": NAVY, "Année en cours": GOLD, "Incomplète": GREY},
                     labels={"annee": "", "recettes": "FCFA"})
        fig.update_traces(texttemplate="%{text:,.0f}", textposition="outside")
        fig.update_yaxes(tickformat=",.0f")
        fig.update_xaxes(type="category")
        st.plotly_chart(_aff(fig, height=380), width="stretch")
    with col2:
        section_title(f"À période égale (janvier–{MOIS_LONGS[m_max - 1]})")
        pe = d.loc[d["mois_num"] <= m_max].groupby("annee")["recettes"].sum().reset_index()
        pe["Évolution"] = pe["recettes"].pct_change() * 100
        fig = px.bar(pe, x="annee", y="recettes", text="recettes", color_discrete_sequence=[NAVY],
                     labels={"annee": "", "recettes": "FCFA"})
        fig.update_traces(texttemplate="%{text:,.0f}", textposition="outside")
        fig.update_yaxes(tickformat=",.0f")
        fig.update_xaxes(type="category")
        st.plotly_chart(_aff(fig, height=380, legend=False), width="stretch")

    section_title("Recettes par mois et par année (millions FCFA)")
    piv = d.pivot_table(index="annee", columns="mois_num", values="recettes", aggfunc="sum") / 1e6
    piv.columns = [MOIS_FR[m - 1] for m in piv.columns]
    fig = px.imshow(piv.round(1), text_auto=True, aspect="auto", color_continuous_scale="Greens",
                    labels=dict(color="M FCFA", x="", y=""))
    fig.update_yaxes(type="category")
    st.plotly_chart(_aff(fig, height=60 + 45 * len(piv), legend=False), width="stretch")

    section_title("Saisonnalité : profil mensuel moyen (mois complets)")
    prof = d_complets.groupby("mois_num")["recettes"].agg(["mean", "min", "max"]).reset_index()
    prof["Mois"] = prof["mois_num"].map(lambda m: MOIS_FR[m - 1])
    fig = go.Figure()
    fig.add_scatter(x=prof["Mois"], y=prof["max"], mode="lines", line=dict(width=0), showlegend=False,
                    hoverinfo="skip")
    fig.add_scatter(x=prof["Mois"], y=prof["min"], mode="lines", line=dict(width=0), fill="tonexty",
                    fillcolor="rgba(20,83,45,0.12)", name="Min–max")
    fig.add_scatter(x=prof["Mois"], y=prof["mean"], mode="lines+markers", name="Moyenne",
                    line=dict(color=NAVY, width=3))
    fig.update_yaxes(title="FCFA", tickformat=",.0f")
    st.plotly_chart(_aff(fig, height=340), width="stretch")

# ----------------------------------------------------------------------------- 3. clients
with onglets[2]:
    fiables = d_complets[~d_complets["libelle"].isin(alertes.loc[alertes["Type"] != "Prix moyen inhabituel", "Mois"])]
    st.caption("Les mois signalés dans « Qualité des données » sont exclus de ces graphiques.")
    col1, col2 = st.columns(2)
    with col1:
        section_title("Clients (moyenne mensuelle)")
        fig = px.line(fiables, x="mois", y="clients", markers=True, color_discrete_sequence=[NAVY],
                      labels={"mois": "", "clients": "Clients"})
        fig.update_yaxes(tickformat=",.0f")
        st.plotly_chart(_aff(fig, height=340, legend=False), width="stretch")
    with col2:
        section_title("Énergie vendue par client (kWh/mois)")
        fig = px.line(fiables, x="mois", y="kwh_par_client", markers=True, color_discrete_sequence=[GOLD],
                      labels={"mois": "", "kwh_par_client": "kWh par client"})
        st.plotly_chart(_aff(fig, height=340, legend=False), width="stretch")
    section_title("Prix moyen de vente (FCFA/kWh)")
    fig = px.line(fiables, x="mois", y="prix_kwh", markers=True, color_discrete_sequence=[GREEN],
                  labels={"mois": "", "prix_kwh": "FCFA/kWh"})
    st.plotly_chart(_aff(fig, height=280, legend=False), width="stretch")

# ----------------------------------------------------------------------------- 4. qualité
with onglets[3]:
    section_title("Contrôles automatiques sur le classeur source")
    if alertes.empty:
        st.success("Aucune anomalie détectée.")
    else:
        st.dataframe(alertes, width="stretch", hide_index=True)
        st.caption("Ces contrôles ne modifient rien : corrige les valeurs dans le classeur source puis recharge-le.")
    mois_attendus = pd.period_range(d_tout["mois"].min(), aujourd_hui, freq="M")
    manquants = sorted(set(mois_attendus) - set(d_tout["mois"].dt.to_period("M")))
    if manquants:
        st.warning("Mois sans données : " + ", ".join(f"{MOIS_FR[p.month - 1]}-{p.year}" for p in manquants))
    else:
        st.info(f"Couverture continue de {MOIS_FR[mois_attendus[0].month - 1]}-{mois_attendus[0].year} "
                f"à {MOIS_FR[mois_attendus[-1].month - 1]}-{mois_attendus[-1].year} : aucun mois manquant.")

# ----------------------------------------------------------------------------- 5. données
with onglets[4]:
    table = d[["libelle", "clients", "energie_kwh", "recettes", "prix_kwh"]].rename(columns={
        "libelle": "Mois", "clients": "Clients (moyenne)", "energie_kwh": "Énergie (kWh)",
        "recettes": "Recettes (FCFA)", "prix_kwh": "Prix moyen (FCFA/kWh)"})
    st.dataframe(table.iloc[::-1], width="stretch", hide_index=True,
                 column_config={"Recettes (FCFA)": st.column_config.NumberColumn(format="localized"),
                                "Énergie (kWh)": st.column_config.NumberColumn(format="localized"),
                                "Clients (moyenne)": st.column_config.NumberColumn(format="localized"),
                                "Prix moyen (FCFA/kWh)": st.column_config.NumberColumn(format="%.1f")})
    st.download_button("⬇️ Exporter en CSV", table.to_csv(index=False, sep=";").encode("utf-8-sig"),
                       "recharges_datacenter.csv", "text/csv")

render_sidebar_footer(data.generated_on if data else "")
