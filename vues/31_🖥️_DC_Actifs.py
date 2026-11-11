import io

import pandas as pd
import streamlit as st

from dc import analyse, depot, modele
from dc.ui import ROLES_GESTION, bandeau, colorer_severite, exiger_lecture, initialiser, peut, style
from utils.ui import PAGE_ICON, inject_base_style, kpi_row, render_sidebar_footer, section_title

st.set_page_config(page_title="Data Center — registre des actifs — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()
exiger_lecture()
initialiser()
style()
bandeau("Registre des actifs du Data Center",
        "Inventaire des équipements : système, emplacement, criticité, état, redondance, garantie et historique")

if st.session_state.get("_dca_ok"):
    st.success("💾 " + st.session_state.pop("_dca_ok"))

eq = depot.equipements()
gestion = peut(ROLES_GESTION)

kpi_row([("Équipements", str(len(eq)), f"{int(eq['quantite'].fillna(1).sum())} unités"),
         ("Critiques", str(int((eq["criticite"] == "Critique").sum())), None),
         ("Points uniques de défaillance", str(int((eq["point_unique"] == "Oui").sum())),
          f"{int((eq['point_unique'] == 'À confirmer').sum())} à confirmer"),
         ("Fiches à compléter", str(int(eq["a_completer"].notna().sum())), None),
         ("En panne / dégradés", str(int(eq["etat"].isin(["En panne", "Dégradé"]).sum())), None)])

t_reg, t_fiche, t_manq = st.tabs(["📋 Registre", "🔎 Fiche d'un équipement", "📝 Informations à compléter"])

with t_reg:
    c1, c2, c3, c4 = st.columns(4)
    fs = c1.multiselect("Système", modele.SYSTEMES, key="dca_s")
    fc = c2.multiselect("Criticité", modele.CRITICITES, key="dca_c")
    fe = c3.multiselect("État", modele.ETATS, key="dca_e")
    fq = c4.text_input("Recherche", key="dca_q")
    v = eq.copy()
    for col, val in (("systeme", fs), ("criticite", fc), ("etat", fe)):
        if val:
            v = v[v[col].isin(val)]
    if fq:
        v = v[v.astype(str).apply(lambda s: s.str.contains(fq, case=False, regex=False)).any(axis=1)]
    colonnes = ["id", "code", "designation", "systeme", "salle", "baie", "fabricant", "modele", "quantite", "criticite",
                "etat", "redondance", "point_unique", "numero_serie", "version", "date_mes", "fin_garantie",
                "fournisseur", "puissance_w", "alias", "a_completer", "observations", "source"]
    config = {"id": None,
              "code": st.column_config.TextColumn("Code", required=True),
              "designation": st.column_config.TextColumn("Désignation", required=True, width="large"),
              "systeme": st.column_config.SelectboxColumn("Système", options=modele.SYSTEMES, required=True),
              "salle": st.column_config.TextColumn("Salle", disabled=True),
              "baie": st.column_config.TextColumn("Baie", disabled=True),
              "criticite": st.column_config.SelectboxColumn("Criticité", options=modele.CRITICITES),
              "etat": st.column_config.SelectboxColumn("État", options=modele.ETATS),
              "point_unique": st.column_config.SelectboxColumn("Point unique", options=["Oui", "Non", "À confirmer"]),
              "date_mes": st.column_config.DateColumn("Mise en service", format="DD/MM/YYYY"),
              "fin_garantie": st.column_config.DateColumn("Fin de garantie", format="DD/MM/YYYY"),
              "puissance_w": st.column_config.NumberColumn("Puissance (W)"),
              "quantite": st.column_config.NumberColumn("Qté", min_value=1, step=1),
              "a_completer": st.column_config.TextColumn("À compléter", width="medium"),
              "source": st.column_config.TextColumn("Source", disabled=True)}
    st.caption(f"{len(v)} équipement(s)." + (" Modifie directement le tableau puis enregistre ; ajoute une ligne pour "
                                              "un nouvel équipement." if gestion else " Lecture seule."))
    ed = st.data_editor(v[colonnes], hide_index=True, width="stretch", height=480, key="dca_ed",
                        num_rows="dynamic" if gestion else "fixed", disabled=not gestion, column_config=config)
    c1, c2 = st.columns([1, 4])
    if gestion and c1.button("💾 Enregistrer", type="primary", key="dca_ok"):
        if ed["code"].duplicated().any() or ed["code"].isin(eq.loc[~eq["id"].isin(v["id"]), "code"]).any():
            st.error("Deux équipements ne peuvent pas avoir le même code.")
        else:
            n = depot.modifier_equipements(eq, ed.drop(columns=["salle", "baie"]))
            st.session_state["_dca_ok"] = f"{n} équipement(s) créé(s) ou modifié(s) ; modifications tracées dans le journal d'audit."
            st.rerun()
    buf = io.BytesIO()
    v[colonnes].drop(columns="id").to_excel(buf, index=False)
    c2.download_button("⬇️ Exporter le registre (Excel)", buf.getvalue(), "registre_actifs_data_center.xlsx", key="dca_dl")

    section_title("RÉPARTITION")
    c1, c2 = st.columns(2)
    c1.dataframe(eq.pivot_table(index="systeme", columns="criticite", values="quantite", aggfunc="sum", fill_value=0)
                 .reindex(columns=[c for c in modele.CRITICITES if c in set(eq["criticite"])]), width="stretch")
    c2.dataframe(eq[eq["point_unique"].isin(["Oui", "À confirmer"])][["code", "designation", "point_unique", "redondance"]]
                 .rename(columns={"code": "Code", "designation": "Désignation", "point_unique": "Point unique",
                                  "redondance": "Redondance"}), hide_index=True, width="stretch")

with t_fiche:
    code = st.selectbox("Équipement", eq["code"].tolist(), key="dca_f",
                        format_func=lambda c: f"{c} — {eq.set_index('code').at[c, 'designation']}")
    e = eq.set_index("code").loc[code]
    c1, c2 = st.columns(2)
    c1.markdown(f"""**{e['designation']}**
- Système : {e['systeme']} · Criticité : **{e['criticite']}** · État : **{e['etat']}**
- Fabricant / modèle : {e['fabricant'] or '—'} {e['modele'] or ''} · Quantité : {int(e['quantite'] or 1)}
- N° de série : {e['numero_serie'] or '—'} · Version : {e['version'] or '—'}
- Redondance : {e['redondance'] or '—'} · Point unique de défaillance : {e['point_unique']}""")
    c2.markdown(f"""- Salle : {e['salle'] or '—'} · Baie : {e['baie'] or '**à compléter**'}
- Mise en service : {pd.Timestamp(e['date_mes']).strftime('%d/%m/%Y') if pd.notna(e['date_mes']) else '—'} ·
  Fin de garantie : {pd.Timestamp(e['fin_garantie']).strftime('%d/%m/%Y') if pd.notna(e['fin_garantie']) else '—'}
- Fournisseur : {e['fournisseur'] or '—'} · Alias : {e['alias'] or '—'}
- Source : {e['source'] or '—'}""")
    if e["observations"]:
        st.info(e["observations"])
    if e["a_completer"]:
        st.warning("À compléter : " + e["a_completer"])
    ctl = depot.controles_pour(e.rename(index=None).to_dict() | {"code": code})
    rel = depot.releves()
    rel_e = rel[rel["equipement_id"] == e["id"]] if len(rel) else rel
    dern = analyse.derniers_releves(rel_e)
    st.markdown(f"**Contrôles applicables : {len(ctl)}**" + ("" if len(ctl) else " — liste de contrôle à créer pour cet équipement."))
    if len(ctl):
        t = ctl[["id", "phase", "point", "frequence", "grandeur"]].merge(
            dern[["controle_id", "date", "statut", "valeur", "severite"]] if len(dern) else
            pd.DataFrame(columns=["controle_id", "date", "statut", "valeur", "severite"]),
            left_on="id", right_on="controle_id", how="left").drop(columns=["id", "controle_id"])
        t["severite"] = t["severite"].fillna("—")
        st.dataframe(t.rename(columns={"phase": "Phase", "point": "Contrôle", "frequence": "Fréquence", "grandeur": "Mesure",
                                       "date": "Dernier relevé", "statut": "Statut", "valeur": "Valeur",
                                       "severite": "Sévérité"}).style.map(colorer_severite, subset=["Sévérité"]),
                     hide_index=True, width="stretch", height=360,
                     column_config={"Dernier relevé": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm")})
    aud = depot.journal_audit(2000)
    aud = aud[(aud["objet"] == "equipement") & (aud["objet_id"] == code)]
    if len(aud):
        st.markdown("**Historique des modifications et inspections**")
        st.dataframe(aud[["horodatage", "utilisateur", "action", "detail"]], hide_index=True, width="stretch",
                     column_config={"horodatage": st.column_config.DatetimeColumn("Date", format="DD/MM/YYYY HH:mm")})

with t_manq:
    m = eq[eq["a_completer"].notna()][["code", "designation", "systeme", "criticite", "a_completer"]]
    st.caption("Informations absentes des documents analysés, à renseigner dans le registre. Elles conditionnent "
               "certaines alertes (ex. taux de charge de l'onduleur, qui nécessite sa puissance en kVA).")
    st.dataframe(m.rename(columns={"code": "Code", "designation": "Désignation", "systeme": "Système",
                                   "criticite": "Criticité", "a_completer": "À compléter"}),
                 hide_index=True, width="stretch", height=480)

render_sidebar_footer("")
