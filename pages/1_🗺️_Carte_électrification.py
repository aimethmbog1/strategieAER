import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from utils.data import NAVY, BLUE, GOLD, RED, GREEN, AMBER, CATEGORICAL
from utils.geo import haversine_km, hierarchy_edges
from utils.loader import get_data
from utils.ui import PAGE_ICON, inject_base_style, section_title, kpi_row, plotly_base_layout, render_sidebar_footer

st.set_page_config(page_title="Carte d'électrification — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()

data = get_data()
if data is None:
    st.stop()

st.title("🗺️ Carte d'électrification — AER")
st.caption(
    "Vue géographique unique du parc solaire : 499 sites, réseau d'antennes, charge de personnel et "
    "distances. Une seule carte, plusieurs couches activables — rien n'est affiché au-delà de ce que "
    "les données du classeur permettent réellement de calculer."
)

sites_all = data.sites
centroids = data.antenna_centroids
if sites_all is None or sites_all.empty:
    st.warning("Feuille « Données sites » introuvable ou vide.")
    st.stop()

with st.expander("ℹ️ Ce que cette carte représente exactement — à lire avant d'interpréter les distances", expanded=False):
    st.markdown(
        "- **Sites** : positionnés à leurs coordonnées GPS réelles (feuille « Données sites »).\n"
        "- **Antennes** (losanges) : l'AER n'a pas fourni les coordonnées du siège de chaque antenne dans ce "
        "classeur. Leur position ici est un **centroïde calculé** — le barycentre des sites qui lui sont "
        "rattachés — une approximation de sa zone de gravité géographique, **pas** l'adresse réelle de "
        "l'antenne.\n"
        "- **Distances** : calculées à vol d'oiseau (formule de Haversine) entre coordonnées GPS réelles. Ce "
        "n'est **pas** une distance routière ni un temps de trajet — ces données ne sont pas dans le classeur, "
        "elles ne sont donc pas affichées ici.\n"
        "- **Personnel affiché sur la carte** : uniquement l'« Effectif recommandé » de la feuille "
        "« Antennes — Détail solaire », qui partage le même référentiel d'antennes que les sites. Le statut "
        "réel des 16 équipes terrain (feuille « Données - Équipes ») utilise un découpage régional différent "
        "(9 antennes nommées par région, pas par ville) qui ne correspond pas antenne pour antenne à celui des "
        "sites — il n'est donc **pas superposé** ici pour ne pas créer un lien géographique trompeur. Ce "
        "détail RH reste disponible sur la page « Équipes terrain »."
    )

# =========================================================================
# Barre de filtres
# =========================================================================
section_title("FILTRES")
f1, f2, f3, f4 = st.columns(4)
antennes = sorted(sites_all["Antenne proposée"].dropna().unique())
regions = sorted(sites_all["Région"].dropna().unique())
phases = sorted(sites_all["Phase"].dropna().unique())

f_antenne = f1.multiselect("Antenne", antennes, default=[], key="map_antenne")
f_region = f2.multiselect("Région", regions, default=[], key="map_region")
f_phase = f3.multiselect("Phase", phases, default=[], key="map_phase")
f_search = f4.text_input("Rechercher un site", key="map_search")

pmin, pmax = float(sites_all["Puissance (kWc)"].min()), float(sites_all["Puissance (kWc)"].max())
f_power = st.slider("Puissance du site (kWc)", min_value=float(np.floor(pmin)), max_value=float(np.ceil(pmax)),
                     value=(float(np.floor(pmin)), float(np.ceil(pmax))), key="map_power")

view = sites_all.copy()
if f_antenne:
    view = view[view["Antenne proposée"].isin(f_antenne)]
if f_region:
    view = view[view["Région"].isin(f_region)]
if f_phase:
    view = view[view["Phase"].isin(f_phase)]
if f_search:
    view = view[view["Nom du site"].astype(str).str.contains(f_search, case=False, na=False)]
view = view[(view["Puissance (kWc)"] >= f_power[0]) & (view["Puissance (kWc)"] <= f_power[1])]

st.caption(f"{len(view)} site(s) affiché(s) sur {len(sites_all)} — "
           f"{view['Puissance (kWc)'].sum():,.0f} kWc au total".replace(",", " "))

c1, c2, c3, c4 = st.columns(4)
with c1:
    color_by = st.selectbox("Colorer les sites par", ["Antenne", "Région", "Phase"], key="map_color_by")
with c2:
    show_antennas = st.checkbox("Afficher les antennes (centroïdes)", value=True, key="map_show_ant")
with c3:
    show_hierarchy = st.checkbox("Afficher la hiérarchie du réseau", value=True, key="map_show_hier")
with c4:
    antenna_by_load = st.checkbox("Colorer les antennes par charge (sites/agent)", value=False, key="map_ant_load")

# =========================================================================
# KPI contextuels — recalculés en direct selon la sélection
# =========================================================================
kpi_row([
    ("Sites (sélection)", f"{len(view):,}".replace(",", " "), None),
    ("Puissance (kWc)", f"{view['Puissance (kWc)'].sum():,.0f}".replace(",", " "), None),
    ("Antennes couvertes", str(view["Antenne proposée"].nunique()), None),
    ("Distance moy. au centre antenne (km)", f"{view['Distance au centre antenne (km)'].mean():.1f}"
     if len(view) else "—", None),
])

st.write("")

# =========================================================================
# Statistiques par phase — recalculées en direct selon la sélection/filtres
# ci-dessus, jamais sur l'ensemble des 499 sites si des filtres sont actifs.
# =========================================================================
if not view.empty:
    section_title("STATISTIQUES PAR PHASE (sélection)")
    phase_stats = (
        view.groupby("Phase", as_index=False)
        .agg(**{"Sites": ("Nom du site", "count"), "Puissance (kWc)": ("Puissance (kWc)", "sum")})
        .sort_values("Phase")
    )
    total_sites = phase_stats["Sites"].sum()
    total_kwc = phase_stats["Puissance (kWc)"].sum()
    phase_stats["% des sites"] = (phase_stats["Sites"] / total_sites * 100).round(1) if total_sites else 0.0
    phase_stats["% de la puissance"] = (
        (phase_stats["Puissance (kWc)"] / total_kwc * 100).round(1) if total_kwc else 0.0
    )

    pc1, pc2, pc3 = st.columns([1, 1, 1.3])
    with pc1:
        fig = go.Figure(data=[go.Pie(
            labels=phase_stats["Phase"], values=phase_stats["Sites"], hole=0.5,
            marker=dict(colors=CATEGORICAL[: len(phase_stats)]), textinfo="label+percent", sort=False,
        )])
        fig.update_layout(title="Sites par phase")
        fig = plotly_base_layout(fig, height=320, legend=False)
        st.plotly_chart(fig, width="stretch")
    with pc2:
        fig = px.bar(phase_stats, x="Phase", y="Puissance (kWc)",
                      color_discrete_sequence=[BLUE], title="Puissance par phase (kWc)")
        fig = plotly_base_layout(fig, height=320, legend=False)
        fig.update_layout(yaxis_title="kWc")
        st.plotly_chart(fig, width="stretch")
    with pc3:
        st.write("")
        st.write("")
        st.dataframe(
            phase_stats[["Phase", "Sites", "% des sites", "Puissance (kWc)", "% de la puissance"]],
            width="stretch", hide_index=True, height=int(38 + 35 * len(phase_stats)),
        )

st.write("")

# =========================================================================
# Carte
# =========================================================================
section_title("CARTE")

color_col_map = {"Antenne": "Antenne proposée", "Région": "Région", "Phase": "Phase"}
color_col = color_col_map[color_by]
map_df = view.dropna(subset=["Latitude (N)", "Longitude (E)"])

fig = go.Figure()

if not map_df.empty:
    categories = sorted(map_df[color_col].dropna().unique())
    palette = CATEGORICAL * (len(categories) // len(CATEGORICAL) + 1)
    for cat, color in zip(categories, palette):
        sub = map_df[map_df[color_col] == cat]
        fig.add_trace(go.Scattermap(
            lat=sub["Latitude (N)"], lon=sub["Longitude (E)"],
            mode="markers",
            marker=dict(
                size=np.clip(sub["Puissance (kWc)"] ** 0.5 * 1.4, 5, 26),
                color=color, opacity=0.8,
            ),
            name=str(cat),
            customdata=sub[["Nom du site", "Région", "Département", "Antenne proposée", "Phase",
                             "Puissance (kWc)", "Distance au centre antenne (km)"]],
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "Antenne : %{customdata[3]}<br>"
                "Région / Département : %{customdata[1]} / %{customdata[2]}<br>"
                "Phase : %{customdata[4]}<br>"
                "Puissance : %{customdata[5]} kWc<br>"
                "Distance au centre antenne : %{customdata[6]} km"
                "<extra></extra>"
            ),
        ))

if show_hierarchy and centroids is not None and not centroids.empty:
    for edge in hierarchy_edges(centroids):
        fig.add_trace(go.Scattermap(
            lat=edge["lat"], lon=edge["lon"], mode="lines",
            line=dict(width=1.6, color=NAVY), opacity=0.55,
            hoverinfo="skip", showlegend=False,
        ))

if show_antennas and centroids is not None and not centroids.empty:
    if antenna_by_load and "Sites par agent" in centroids.columns:
        marker = dict(
            size=np.clip(centroids["Nb_sites_reels"] ** 0.5 * 2.2, 14, 40),
            color=centroids["Sites par agent"], colorscale=[[0, BLUE], [1, RED]],
            colorbar=dict(title="Sites / agent", x=1.02), showscale=True,
        )
    else:
        marker = dict(size=np.clip(centroids["Nb_sites_reels"] ** 0.5 * 2.2, 14, 40), color=NAVY)
    marker["symbol"] = "diamond"
    ant_custom = centroids[["Antenne", "Type", "Rattachée à", "Nb_sites_reels", "Puissance_totale",
                             "Effectif total", "Sites par agent"]].fillna("—")
    fig.add_trace(go.Scattermap(
        lat=centroids["Latitude"], lon=centroids["Longitude"], mode="markers+text",
        marker=marker, text=centroids["Antenne"].str.replace("Antenne ", "", regex=False),
        textposition="top center", textfont=dict(size=10, color=NAVY),
        name="Antenne (centroïde)",
        customdata=ant_custom,
        hovertemplate=(
            "<b>%{customdata[0]}</b> (%{customdata[1]})<br>"
            "Rattachée à : %{customdata[2]}<br>"
            "Sites réels géolocalisés : %{customdata[3]}<br>"
            "Puissance totale : %{customdata[4]:.0f} kWc<br>"
            "Effectif recommandé : %{customdata[5]}<br>"
            "Charge (sites/agent) : %{customdata[6]}"
            "<extra></extra>"
        ),
    ))

# --- Outil de mesure de distance (superposé sur la carte si activé) ---
st.write("")
with st.expander("📏 Outil — mesurer la distance entre deux sites (à vol d'oiseau)"):
    names = sorted(sites_all["Nom du site"].dropna().unique())
    dc1, dc2 = st.columns(2)
    site_a = dc1.selectbox("Site A", names, index=None, placeholder="Choisir un site…", key="dist_a")
    site_b = dc2.selectbox("Site B", names, index=None, placeholder="Choisir un site…", key="dist_b")
    if site_a and site_b and site_a != site_b:
        ra = sites_all[sites_all["Nom du site"] == site_a].iloc[0]
        rb = sites_all[sites_all["Nom du site"] == site_b].iloc[0]
        d = haversine_km(ra["Latitude (N)"], ra["Longitude (E)"], rb["Latitude (N)"], rb["Longitude (E)"])
        st.success(f"**{site_a}** ↔ **{site_b}** : **{d:.1f} km** à vol d'oiseau "
                   f"({ra['Antenne proposée']} → {rb['Antenne proposée']}).")
        fig.add_trace(go.Scattermap(
            lat=[ra["Latitude (N)"], rb["Latitude (N)"]], lon=[ra["Longitude (E)"], rb["Longitude (E)"]],
            mode="lines+markers", line=dict(width=3, color=RED),
            marker=dict(size=11, color=RED), name=f"{site_a} ↔ {site_b}",
            hoverinfo="skip",
        ))
    elif site_a and site_b and site_a == site_b:
        st.info("Choisissez deux sites différents.")

center_lat = map_df["Latitude (N)"].mean() if not map_df.empty else 5.5
center_lon = map_df["Longitude (E)"].mean() if not map_df.empty else 12.5
fig.update_layout(
    map=dict(style="carto-positron", center=dict(lat=center_lat, lon=center_lon), zoom=5.3),
    height=680, margin=dict(l=0, r=0, t=0, b=0),
    legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0),
)
st.plotly_chart(fig, width="stretch", key="electrification_map")

# =========================================================================
# Sites les plus isolés (distance au centre de leur antenne)
# =========================================================================
st.write("")
section_title("SITES LES PLUS ÉLOIGNÉS DU CENTRE DE LEUR ANTENNE")
st.caption("Le centre d'antenne est le centroïde calculé ci-dessus, pas son adresse réelle — à lire comme un "
           "indicateur de dispersion géographique du parc, pas comme une distance de trajet garantie.")
top_n = st.slider("Nombre de sites à afficher", 5, 30, 10, key="map_topn")
isolated = view.sort_values("Distance au centre antenne (km)", ascending=False).head(top_n)
st.dataframe(
    isolated[["Nom du site", "Antenne proposée", "Région", "Département", "Phase",
              "Puissance (kWc)", "Distance au centre antenne (km)"]],
    width="stretch", hide_index=True,
)

# =========================================================================
# Fréquence de visite (référentiel RH — non géolocalisé, surfacé tel quel)
# =========================================================================
if data.visites_mensuelles is not None and not data.visites_mensuelles.empty:
    with st.expander("🧭 Fréquence de visite mensuelle proposée (feuille « Synthèse par région », "
                      "référentiel RH — non géolocalisable sur cette carte)"):
        st.caption("Cette table utilise le découpage par région du fichier RH, différent du découpage par "
                   "antenne des sites ci-dessus (voir l'encadré méthodologique en haut de page) — elle est "
                   "affichée telle quelle, sans tentative de la superposer géographiquement au parc solaire.")
        st.dataframe(data.visites_mensuelles, width="stretch", hide_index=True)

# =========================================================================
# Table complète (avec distance) + export
# =========================================================================
st.write("")
section_title("TABLEAU DÉTAILLÉ DE LA SÉLECTION")
st.dataframe(view.sort_values("Distance au centre antenne (km)", ascending=False),
             width="stretch", hide_index=True, height=420)
st.download_button("⬇️ Télécharger cette sélection (CSV, avec distances)",
                    view.to_csv(index=False).encode("utf-8"), "sites_carte_electrification.csv", "text/csv")

render_sidebar_footer(data.generated_on)
