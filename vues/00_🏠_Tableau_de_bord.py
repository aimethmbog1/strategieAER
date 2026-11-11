import pandas as pd
import plotly.express as px
import streamlit as st

from utils.data import BLUE, GOLD, NAVY, RED
from utils.loader import get_data
from utils.synthese import blocs, fcfa, nb
from utils.ui import PAGE_ICON, inject_base_style, plotly_base_layout, render_sidebar_footer, section_title

st.set_page_config(page_title="Tableau de bord — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()
data = get_data()
if data is None:
    st.stop()

st.markdown("""<style>
.tb-carte h4{margin:0 0 .35rem 0;font-size:1.02rem}
.tb-k{display:flex;justify-content:space-between;align-items:baseline;border-bottom:1px solid #EEF2EF;padding:.28rem 0;gap:.6rem}
.tb-k span{color:#4B5563;font-size:.86rem}
.tb-k b{color:#052E16;font-size:1.02rem;white-space:nowrap}
.tb-k small{display:block;color:#6B7280;font-weight:400;font-size:.74rem;text-align:right}
.tb-note{color:#6B7280;font-size:.8rem;margin-top:.3rem}
.tb-bandeau{background:linear-gradient(90deg,#14532D,#1F3864);color:#fff;border-radius:14px;padding:1rem 1.3rem;margin-bottom:.8rem}
.tb-ruban{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.7rem;margin:.2rem 0 .6rem 0}
.tb-cle{background:#fff;border:1px solid #E5E7EB;border-radius:14px;padding:.75rem .9rem;box-shadow:0 1px 4px rgba(5,46,22,.06)}
.tb-cle span{display:block;color:#4B5563;font-size:.82rem;font-weight:600}
.tb-cle b{display:block;color:#052E16;font-size:1.45rem;line-height:1.3;white-space:nowrap}
.tb-cle small{color:#6B7280;font-size:.75rem}
.tb-bandeau h2{color:#fff;margin:0;font-size:1.45rem}.tb-bandeau p{margin:.2rem 0 0 0;opacity:.9;font-size:.9rem}
</style>""", unsafe_allow_html=True)

auj = pd.Timestamp.now(tz="Africa/Douala")
st.markdown(f"""<div class="tb-bandeau"><h2>Tableau de bord de l'Agence d'Électrification Rurale</h2>
<p>Synthèse de tous les modules de l'application · situation au {auj:%d/%m/%Y à %H:%M} (heure de Douala)</p></div>""",
            unsafe_allow_html=True)

with st.spinner("Calcul des indicateurs de tous les modules…"):
    bl = blocs(data)
par_nom = {b.domaine: b for b in bl}

# ----------------------------------------------------------------------------- bandeau d'indicateurs clés
cles = []
for dom, lib in [("Parc solaire en exploitation", "En service"), ("Parc solaire en exploitation", "Puissance en service"),
                 ("Maintenance (GMAO)", "BI ouverts"), ("Alertes", "Critique"), ("Recharges Data Center", None),
                 ("Équipes terrain", "Postes pourvus / requis")]:
    b = par_nom.get(dom)
    if not b or not b.kpis:
        continue
    k = next((x for x in b.kpis if lib is None or x[0] == lib), None)
    if k:
        cles.append((("Alertes critiques" if dom == "Alertes" else k[0]), k[1], k[2]))
COURTS = {"Postes pourvus / requis": "Postes pourvus", "Puissance en service": "kWc en service"}
st.markdown("<div class='tb-ruban'>" + "".join(
    f"<div class='tb-cle'><span>{COURTS.get(l, l)}</span><b>{v}</b><small>{d or '&nbsp;'}</small></div>"
    for l, v, d in cles) + "</div>", unsafe_allow_html=True)

# ----------------------------------------------------------------------------- cartes par domaine
section_title("SITUATION PAR DOMAINE")


def carte(b):
    with st.container(border=True):
        st.markdown(f"<div class='tb-carte'><h4>{b.icone} {b.domaine}</h4></div>", unsafe_allow_html=True)
        if b.kpis:
            st.markdown("".join(f"<div class='tb-k'><span>{l}</span><b>{v}{f'<small>{d}</small>' if d else ''}</b></div>"
                                for l, v, d in b.kpis), unsafe_allow_html=True)
        if b.note or b.etat != "ok":
            st.markdown(f"<div class='tb-note'>{b.note or 'Aucune donnée pour le moment.'}</div>", unsafe_allow_html=True)
        if b.page:
            try:
                st.page_link(b.page, label="Ouvrir le module", icon="➡️")
            except Exception:  # noqa: BLE001 — page absente du menu (droits) ou exécution hors navigation
                pass


for i in range(0, len(bl), 3):
    cs = st.columns(3)
    for c, b in zip(cs, bl[i:i + 3]):
        with c:
            carte(b)

# ----------------------------------------------------------------------------- graphiques transversaux
section_title("TENDANCES ET RÉPARTITIONS")
c1, c2 = st.columns(2)
parc = par_nom.get("Parc solaire en exploitation")
with c1:
    cl = getattr(parc, "extra", None)
    if cl is not None:
        from utils import maintenance as mt
        ref = mt.referentiel_sites(data.sites).assign(etat=lambda d: d["site_id"].map(cl))
        t = ref.groupby(["Phase", "etat"]).size().reset_index(name="Centrales")
        fig = px.bar(t, x="Phase", y="Centrales", color="etat", text="Centrales", title="État du parc par phase",
                     color_discrete_map={"Fonctionnelle (H24)": "#27AE60", "Fonctionnement partiel": "#E67E22",
                                         "À l'arrêt": RED, "Non renseigné": "#C7CCD1"},
                     category_orders={"etat": ["Fonctionnelle (H24)", "Fonctionnement partiel", "À l'arrêt", "Non renseigné"]})
        fig.update_layout(barmode="stack", legend=dict(orientation="h", y=-0.25, title=None))
        st.plotly_chart(plotly_base_layout(fig, height=360), width="stretch")
with c2:
    d = getattr(par_nom.get("Recharges Data Center"), "extra", None)
    if d is not None and len(d):
        an = int(d["annee"].max())
        x = d[d["annee"] >= an - 2].copy()
        x["Année"] = x["annee"].astype(str)
        fig = px.line(x, x="mois_num", y="recettes", color="Année", markers=True, title="Recettes mensuelles du Data Center",
                      labels={"mois_num": "Mois", "recettes": "FCFA"}, color_discrete_sequence=[GOLD, BLUE, NAVY])
        fig.update_xaxes(tickmode="array", tickvals=list(range(1, 13)),
                         ticktext=["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"])
        fig.update_layout(separators=", ", legend=dict(orientation="h", y=-0.25))
        st.plotly_chart(plotly_base_layout(fig, height=360), width="stretch")

al = getattr(par_nom.get("Alertes"), "extra", None)
if al is not None and not al.empty:
    c1, c2 = st.columns([2, 3])
    with c1:
        t = al.groupby(["Domaine", "Gravité"]).size().reset_index(name="Alertes")
        fig = px.bar(t, y="Domaine", x="Alertes", color="Gravité", orientation="h", title="Alertes par domaine",
                     color_discrete_map={"Critique": RED, "Élevée": "#E67E22", "Moyenne": BLUE, "Information": "#9CA3AF"},
                     category_orders={"Gravité": ["Critique", "Élevée", "Moyenne", "Information"]})
        fig.update_layout(legend=dict(orientation="h", y=-0.25, title=None))
        fig.update_yaxes(title=None, categoryorder="total ascending")
        st.plotly_chart(plotly_base_layout(fig, height=360), width="stretch")
    with c2:
        st.markdown("**Points prioritaires**")
        ordre = {"Critique": 0, "Élevée": 1, "Moyenne": 2, "Information": 3}
        top = al.assign(o=al["Gravité"].map(ordre)).sort_values("o").drop(columns="o").head(10)
        st.dataframe(top, hide_index=True, width="stretch", height=330)

st.caption("Chaque indicateur est calculé à partir des registres enregistrés dans la base et du classeur de référence ; "
           "un module sans données l'indique au lieu d'afficher une valeur par défaut. "
           f"Classeur de référence : {data.generated_on or '—'}.")
render_sidebar_footer(data.generated_on)
