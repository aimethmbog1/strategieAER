from datetime import timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from dc import analyse, depot, modele
from dc.regles import autonomie_estimee_min
from dc.ui import (COULEURS, ICONES, ROLES_SENSIBLE, bandeau, colorer_severite, exiger_lecture, initialiser, peut, style)
from utils.ui import PAGE_ICON, inject_base_style, kpi_row, plotly_base_layout, render_sidebar_footer, section_title

st.set_page_config(page_title="Data Center — tableau de bord — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()
exiger_lecture()
initialiser()
style()

auj = depot.maintenant()
bandeau("Data Center FM800 — tableau de bord",
        f"Huawei FusionModule800 · salle des serveurs · situation au {auj:%d/%m/%Y à %H:%M} (heure de Douala)")

eq = depot.equipements()
ctl = depot.controles()
rel = depot.releves()
ec = analyse.ecarts_ouverts(rel)
plan = analyse.plan_controles(eq, ctl, rel, auj)
ind = analyse.indicateurs(plan, rel, auj - timedelta(days=30))

batt = eq[eq["code"] == "FM800-BATT"]
charge = eq.loc[eq["puissance_w"].notna(), "puissance_w"].mul(eq["quantite"].fillna(1)).sum()
kpi_row([
    ("Équipements suivis", str(len(eq)), f"{int(eq['a_completer'].notna().sum())} fiches à compléter"),
    ("Écarts critiques", str(int((ec['severite'] == 'Critique').sum()) if len(ec) else 0), None),
    ("Avertissements", str(int((ec['severite'] == 'Avertissement').sum()) if len(ec) else 0), None),
    ("Contrôles en retard", f"{ind['en_retard']} / {ind['controles']}",
     f"respect du plan : {ind['respect_plan']:.1f} %".replace(".", ",") if ind["respect_plan"] is not None else None),
    ("Conformité (30 jours)", f"{ind['conformite']:.1f} %".replace(".", ",") if ind["conformite"] is not None else "—",
     f"{ind['inspections']} inspection(s)"),
    ("Autonomie onduleur", "90 min", "mesurée le 13/07/2026 (≈ 5,2 kW)"),
])

# ----------------------------------------------------------------------------- état par système
section_title("ÉTAT PAR SYSTÈME")
etat = analyse.etat_systemes(eq, ec, modele.SYSTEMES)
cols = st.columns(4)
for i, r in etat.iterrows():
    with cols[i % 4]:
        sev = r["État"]
        st.markdown(f"<div class='dc-sys' style='background:{COULEURS.get(sev, '#9CA3AF')}'><b>{ICONES.get(sev, '⚪')} "
                    f"{r['Système']}</b><span>{r['Équipements']} équipement(s) · {r['Écarts ouverts']} écart(s) ouvert(s)"
                    f"<br>{r['En panne / dégradés']} en panne ou dégradé(s) · {r['Informations à compléter']} à compléter"
                    f"</span></div>", unsafe_allow_html=True)
        st.write("")

# ----------------------------------------------------------------------------- tâches du jour et écarts
c1, c2 = st.columns([3, 2])
with c1:
    section_title("TÂCHES DU JOUR — CONTRÔLES DUS")
    if plan.empty:
        st.info("Aucun contrôle planifié.")
    else:
        dus = plan[plan["en_retard"]].groupby(["code", "frequence"]).size().reset_index(name="Contrôles dus")
        ordre = {f: i for i, f in enumerate(modele.FREQUENCES)}
        dus = dus.assign(o=dus["frequence"].map(ordre)).sort_values(["o", "code"]).drop(columns="o")
        st.dataframe(dus.rename(columns={"code": "Équipement", "frequence": "Fréquence"}), hide_index=True,
                     width="stretch", height=330)
        try:
            st.page_link("vues/32_🖥️_DC_Inspections.py", label="Réaliser une inspection", icon="📝")
        except Exception:  # noqa: BLE001 — hors navigation (tests)
            pass
with c2:
    section_title("ÉCARTS OUVERTS")
    if ec.empty:
        st.success("Aucun écart ouvert.")
    else:
        codes = dict(zip(eq["id"], eq["code"]))
        v = ec.assign(Équipement=ec["equipement_id"].map(codes))
        st.dataframe(v[["severite", "Équipement", "point", "valeur", "date"]].rename(columns={
            "severite": "Sévérité", "point": "Contrôle", "valeur": "Valeur", "date": "Relevé le"}).style.map(
            colorer_severite, subset=["Sévérité"]), hide_index=True, width="stretch", height=330,
            column_config={"Relevé le": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm")})

# ----------------------------------------------------------------------------- inventaire et alimentation
c1, c2 = st.columns(2)
with c1:
    section_title("INVENTAIRE PAR SYSTÈME ET CRITICITÉ")
    t = eq.groupby(["systeme", "criticite"])["quantite"].sum().reset_index()
    fig = px.bar(t, y="systeme", x="quantite", color="criticite", orientation="h",
                 color_discrete_map={"Critique": COULEURS["Critique"], "Haute": COULEURS["Avertissement"],
                                     "Moyenne": "#2563EB", "Basse": "#9CA3AF"},
                 labels={"systeme": "", "quantite": "Unités", "criticite": "Criticité"})
    fig.update_yaxes(categoryorder="total ascending")
    fig.update_layout(legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(plotly_base_layout(fig, height=340), width="stretch")
with c2:
    section_title("ALIMENTATION SECOURUE")
    est = autonomie_estimee_min(8640, charge) if charge else None
    st.markdown(f"""
- **Onduleur** : Huawei UPS2000G intégré au FusionModule800 — puissance (kVA) **à compléter**
- **Batteries** : 4 packs LiFePO4, 8 640 Wh, installées le 07/05/2026
- **Charge estimée** des équipements recensés : **{charge:,.0f} W**""".replace(",", " ") + (
        f" (puissances constructeur) → autonomie théorique ≈ **{est:.0f} min**, prudente par rapport aux 90 min "
        "mesurées" if est else "") + """
- **Dernier essai** : 13/07/2026 — 90 min de 100 % à 10 %, aucune alarme (arrêt des services de 1 h 43 à la fin du test)
- **Groupe électrogène** : caractéristiques **à compléter**""")
    spof = eq[eq["point_unique"] == "Oui"]
    if len(spof):
        st.warning("Points uniques de défaillance déclarés : " + ", ".join(spof["code"]))

# ----------------------------------------------------------------------------- sécurité (accès restreint)
cst = depot.constats()
if len(cst):
    section_title("ACTIONS CORRECTIVES ISSUES DE LA CARTOGRAPHIE")
    ouv = cst[cst["statut"] != "Clôturé"]
    st.caption(f"{len(ouv)} constat(s) non clôturé(s) sur {len(cst)} — dont "
               f"{int((ouv['nature'].str.lower().str.startswith('s')).sum())} de sécurité.")
    if peut(ROLES_SENSIBLE):
        st.dataframe(ouv[["numero", "nature", "constat", "statut", "responsable", "echeance"]], hide_index=True,
                     width="stretch", column_config={"echeance": st.column_config.DateColumn("Échéance", format="DD/MM/YYYY")})

section_title("DERNIÈRES INSPECTIONS")
ins = depot.inspections()
if ins.empty:
    st.info("Aucune inspection enregistrée.")
else:
    codes = dict(zip(eq["id"], eq["code"]))
    nb = rel.groupby("inspection_id")["severite"].agg(lambda s: f"{(s == 'OK').sum()} OK · {(s != 'OK').sum()} écart(s)")
    v = ins.sort_values("date", ascending=False).head(10).assign(Équipement=lambda d: d["equipement_id"].map(codes),
                                                                  Résultat=lambda d: d["id"].map(nb))
    st.dataframe(v[["date", "Équipement", "frequence", "inspecteur", "Résultat"]], hide_index=True, width="stretch",
                 column_config={"date": st.column_config.DatetimeColumn("Date", format="DD/MM/YYYY HH:mm")})

render_sidebar_footer("")
