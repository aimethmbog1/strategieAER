import plotly.graph_objects as go
import streamlit as st

from utils.data import GOLD, GREEN, AMBER, RED
from utils.loader import get_data
from utils.personnel import (
    appliquer_mouvement, couverture_par_antenne, destination_options,
    effectif_actuel_par_antenne, enregistrer_mouvement, get_effective_roster, get_mouvements,
    personnel_options, reinitialiser_mouvements,
)
from utils.ui import (
    BRAND, BRAND_DARK, HEADING_FONT, PAGE_ICON, inject_base_style, section_title,
    plotly_base_layout, kpi_row, render_sidebar_footer,
)

st.set_page_config(page_title="Organigramme — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()

data = get_data()
if data is None:
    st.stop()

eq_effectif, unassigned_effectif = get_effective_roster(data.equipes_rows, data.unassigned)

st.title("🏢 Organigramme du réseau d'antennes")
st.caption("Reconstruit dynamiquement à partir de la feuille « Antennes — Détail solaire » "
           "(colonnes Antenne / Type / Rattachée à / Effectif total) — aucune dépendance système "
           "requise (rendu 100% Plotly, contrairement à Graphviz). Le personnel peut être "
           "réaffecté directement depuis cette page (section « Mouvement de personnel » ci-dessous) : "
           "l'effectif réel par antenne se met à jour immédiatement, ici comme sur les pages "
           "« Équipes terrain », « Home » et « Parc automobile ».")

det = data.antennes_detail
if det is None or det.empty or "Rattachée à" not in det.columns:
    st.warning("Impossible de reconstruire l'organigramme : colonnes attendues introuvables.")
    st.stop()

# =========================================================================
# 1) Siège & antennes du parc SOLAIRE — effectif RECOMMANDÉ (inchangé, 100%
#    issu de la feuille « Antennes — Détail solaire »). Forme et typographie
#    retravaillées (demande explicite) : sunburst plutôt qu'icicle, police
#    Outfit, teintes de marque.
# =========================================================================
section_title("SIÈGE & ANTENNES — VUE HIÉRARCHIQUE (parc solaire, effectif recommandé)")

SIEGE_LABEL = "AGENCE D'ÉLECTRIFICATION RURALE — Siège Yaoundé"
ids, labels, parents, values, colors, custom = [], [], [], [], [], []

ids.append("SIEGE"); labels.append(SIEGE_LABEL); parents.append("")
values.append(0); colors.append(BRAND_DARK); custom.append("")

for _, row in det.iterrows():
    antenne = str(row.get("Antenne") or "").strip()
    if not antenne:
        continue
    typ = row.get("Type") or ""
    effectif = row.get("Effectif total") or 0
    sites = row.get("Nb sites") or 0
    parent = row.get("Rattachée à")
    parent_id = str(parent).strip() if parent and str(parent).strip() not in ("—", "None", "") else "SIEGE"
    ids.append(antenne)
    labels.append(antenne)
    parents.append(parent_id)
    values.append(max(effectif, 1))
    colors.append(BRAND if typ == "Principale" else GOLD)
    custom.append(f"{typ} · {int(sites)} sites · {int(effectif)} agents recommandés")

fig = go.Figure(go.Sunburst(
    ids=ids, labels=labels, parents=parents, values=values,
    marker=dict(colors=colors, line=dict(width=2, color="white")),
    customdata=custom,
    hovertemplate="<b>%{label}</b><br>%{customdata}<extra></extra>",
    insidetextorientation="radial",
    textfont=dict(family=HEADING_FONT, size=14, color="white"),
    maxdepth=3,
))
fig = plotly_base_layout(fig, height=560, legend=False)
fig.update_layout(margin=dict(t=10, l=10, r=10, b=10), font=dict(family=HEADING_FONT))
st.plotly_chart(fig, width="stretch")

st.caption(f"🟢 Antenne principale &nbsp;&nbsp; 🟡 Annexe rattachée &nbsp;&nbsp;"
           " — la taille de chaque secteur est proportionnelle à son **effectif recommandé** "
           "(feuille solaire — cible, pas l'effectif réel actuel).")

with st.expander("Voir le tableau source (parc solaire)"):
    st.dataframe(det[["Antenne", "Type", "Rattachée à", "Nb sites", "Effectif total"]],
                 width="stretch", hide_index=True)

st.write("")

# =========================================================================
# 2) Répartition ACTUELLE du personnel — référentiel RH (feuille
#    « Données - Équipes »). ATTENTION : cette feuille utilise 9 antennes
#    nommées PAR RÉGION, un découpage différent des antennes du parc solaire
#    ci-dessus (nommées par ville) — les deux ne se recouvrent pas antenne
#    pour antenne (même limite déjà documentée sur les pages « Carte
#    électrification » et « Parc automobile »). On ne les superpose donc
#    jamais : ce deuxième schéma reste dans son propre référentiel RH, à
#    plat (le classeur ne fournit aucune colonne de rattachement hiérarchique
#    entre antennes RH, contrairement à la feuille solaire).
# =========================================================================
section_title("RÉPARTITION ACTUELLE DU PERSONNEL PAR ANTENNE (référentiel RH)")
st.caption(
    "⚠️ Référentiel **différent** du schéma ci-dessus : la feuille « Données - Équipes » découpe le "
    "personnel en 9 antennes nommées **par région** (Nord, Adamaoua, Est…), pas par ville comme les "
    "antennes du parc solaire — les deux listes ne correspondent pas une à une. Affiché ici à plat "
    "(aucune colonne du classeur n'indique de rattachement hiérarchique entre antennes RH). La taille de "
    "chaque secteur reflète l'**effectif réellement en poste maintenant**, mouvements de personnel inclus."
)

couverture = couverture_par_antenne(eq_effectif)
effectif_actuel = effectif_actuel_par_antenne(eq_effectif)

if couverture.empty:
    st.info("Feuille « Données - Équipes » introuvable ou vide — impossible de construire ce schéma.")
else:
    def _status_color(taux: float) -> str:
        if taux >= 90:
            return GREEN
        if taux >= 50:
            return AMBER
        return RED

    ids2 = ["SIEGE_RH"]
    labels2 = ["Personnel AER — toutes antennes RH"]
    parents2 = [""]
    values2 = [0]
    colors2 = [BRAND_DARK]
    custom2 = [""]
    for _, row in couverture.iterrows():
        antenne = row["Antenne"]
        ids2.append(antenne)
        labels2.append(antenne.replace("Antenne ", "").replace("Annexe ", "Annexe "))
        parents2.append("SIEGE_RH")
        values2.append(max(int(row["Effectif total (avec additionnel)"]), 1))
        colors2.append(_status_color(row["Taux de couverture (%)"]))
        custom2.append(
            f"{int(row['Effectif total (avec additionnel)'])} agent(s) en poste · "
            f"{int(row['Pourvus'])}/{int(row['Postes-types suivis'])} postes-types pourvus "
            f"({row['Taux de couverture (%)']:.0f} %)"
        )

    fig2 = go.Figure(go.Sunburst(
        ids=ids2, labels=labels2, parents=parents2, values=values2,
        marker=dict(colors=colors2, line=dict(width=2, color="white")),
        customdata=custom2,
        hovertemplate="<b>%{label}</b><br>%{customdata}<extra></extra>",
        insidetextorientation="radial",
        textfont=dict(family=HEADING_FONT, size=14, color="white"),
    ))
    fig2 = plotly_base_layout(fig2, height=560, legend=False)
    fig2.update_layout(margin=dict(t=10, l=10, r=10, b=10), font=dict(family=HEADING_FONT))
    st.plotly_chart(fig2, width="stretch")

    st.caption("🟢 Postes-types ≥ 90% pourvus &nbsp;&nbsp; 🟠 50–90% &nbsp;&nbsp; 🔴 < 50% — "
               "couleur recalculée en direct selon les mouvements de personnel appliqués cette session.")

    with st.expander("Voir le détail par antenne RH (couverture des postes-types)"):
        st.dataframe(couverture, width="stretch", hide_index=True)

st.write("")

# =========================================================================
# 3) Mouvement de personnel — assigner un agent (équipe ou pool non affecté)
#    vers un autre poste. Session uniquement, comme les autres registres
#    éditables de l'application (parc auto, fonds revolving, suivi de
#    projets) : jamais écrit dans le classeur source.
# =========================================================================
section_title("↔️ MOUVEMENT DE PERSONNEL")
st.caption(
    "Déplacez un agent — y compris depuis le **personnel non affecté à une équipe** — vers un autre "
    "poste. Les pages « Équipes terrain », l'onglet RH de Home et les besoins d'acquisition de véhicules "
    "(liés aux chauffeurs réels) se mettent à jour automatiquement. Non persisté entre deux sessions : "
    "le classeur source n'est jamais modifié."
)

opts_source = personnel_options(eq_effectif, unassigned_effectif)
if not opts_source:
    st.info("Aucun agent déplaçable trouvé (feuille « Données - Équipes » vide).")
else:
    mc1, mc2 = st.columns(2)
    with mc1:
        src_choice = st.selectbox(
            "Agent à déplacer", opts_source, format_func=lambda o: o["label"], index=None,
            placeholder="Choisir un agent…", key="mv_source",
        )
    with mc2:
        opts_dest_all = destination_options(eq_effectif)
        if src_choice is not None:
            opts_dest = [
                o for o in opts_dest_all
                if not (o["target"] == "equipe" and src_choice["source"] == "equipe" and o["index"] == src_choice["index"])
                and not (o["target"] == "pool" and src_choice["source"] == "pool")
            ]
        else:
            opts_dest = opts_dest_all
        dst_choice = st.selectbox(
            "Nouveau poste", opts_dest, format_func=lambda o: o["label"], index=None,
            placeholder="Choisir un poste de destination…", key="mv_dest", disabled=src_choice is None,
        )

    if st.button("Déplacer", type="primary", disabled=src_choice is None or dst_choice is None):
        new_eq, new_pool, desc = appliquer_mouvement(eq_effectif, unassigned_effectif, src_choice, dst_choice)
        st.session_state["personnel_equipes"] = new_eq
        st.session_state["personnel_unassigned"] = new_pool
        enregistrer_mouvement(desc)
        st.success(desc)
        st.rerun()

mouvements = get_mouvements()
with st.expander(f"Journal des mouvements de cette session ({len(mouvements)})"):
    if mouvements.empty:
        st.caption("Aucun mouvement appliqué pour l'instant.")
    else:
        st.dataframe(mouvements.sort_index(ascending=False), width="stretch", hide_index=True)
        if st.button("↩️ Réinitialiser tous les mouvements (revenir au classeur source)"):
            reinitialiser_mouvements()
            st.rerun()

render_sidebar_footer(data.generated_on)
