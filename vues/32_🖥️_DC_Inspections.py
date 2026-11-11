import base64
import io
from datetime import timedelta

import pandas as pd
import streamlit as st

from dc import analyse, depot, modele
from dc.ui import ROLES_INSPECTION, bandeau, colorer_severite, exiger_lecture, initialiser, peut, style
from utils.auth import utilisateur
from utils.ui import PAGE_ICON, inject_base_style, kpi_row, render_sidebar_footer, section_title

st.set_page_config(page_title="Data Center — inspections — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()
exiger_lecture()
initialiser()
style()
bandeau("Inspections du Data Center",
        "Rondes et listes de contrôle par équipement et par fréquence ; les écarts sont détectés automatiquement "
        "à partir des seuils")

if st.session_state.get("_dci_ok"):
    b = st.session_state.pop("_dci_ok")
    (st.error if b["Critique"] else st.warning if b["Avertissement"] else st.success)(
        f"Inspection n° {b['id']} enregistrée : {b['OK']} conforme(s), {b['Avertissement']} avertissement(s), "
        f"{b['Critique']} écart(s) critique(s).")

auj = depot.maintenant()
eq = depot.equipements()
ctl_all = depot.controles()
rel = depot.releves()
sl = depot.seuils()
plan = analyse.plan_controles(eq, ctl_all, rel, auj)
avec_ctl = sorted(plan["code"].unique()) if len(plan) else []

t_new, t_plan, t_hist = st.tabs(["📝 Nouvelle inspection", "🗓️ Plan des contrôles", "📚 Historique"])

# ============================================================================= NOUVELLE INSPECTION
with t_new:
    if not peut(ROLES_INSPECTION):
        st.info("🔒 Votre profil permet de consulter les inspections, pas d'en saisir.")
    else:
        dus = plan[plan["en_retard"]].groupby("code").size() if len(plan) else pd.Series(dtype=int)
        c1, c2, c3 = st.columns([3, 2, 2])
        code = c1.selectbox("Équipement", avec_ctl, key="dci_eq",
                            format_func=lambda c: f"{c} — {eq.set_index('code').at[c, 'designation']}"
                            + (f"  ·  {dus.get(c)} dû(s)" if dus.get(c) else ""))
        e = eq.set_index("code").loc[code]
        ctl = depot.controles_pour(e.to_dict() | {"code": code}, ctl_all)
        freqs = [f for f in modele.FREQUENCES if f in set(ctl["frequence"])]
        freq = c2.selectbox("Fréquence", ["Contrôles dus"] + freqs + ["Tous"], key=f"dci_f_{code}")
        p = plan[(plan["code"] == code)]
        if freq == "Contrôles dus":
            ids = set(p.loc[p["en_retard"], "controle_id"])
            ctl = ctl[ctl["id"].isin(ids)]
        elif freq != "Tous":
            ctl = ctl[ctl["frequence"] == freq]
        c3.metric("Contrôles à saisir", len(ctl))
        if ctl.empty:
            st.success("Aucun contrôle dû pour cet équipement. Choisis une fréquence pour refaire un contrôle.")
        else:
            u = utilisateur() or {}
            n = st.session_state.get("_dci_n", 0)
            with st.form(f"dci_form_{code}_{freq}_{n}"):
                saisies = []
                for phase, g in ctl.groupby("phase", sort=False):
                    st.markdown(f"**{phase}**")
                    for c in g.itertuples():
                        with st.container(border=True):
                            a, b = st.columns([3, 2])
                            a.markdown(f"**{c.point}**" + (f"  \n`{c.commande}`" if c.commande else ""))
                            a.caption(f"Normal : {c.normal or '—'}  \nÀ signaler : {c.a_signaler or '—'}")
                            statut = b.radio("Résultat", modele.STATUTS_CONTROLE, horizontal=True, key=f"s_{c.id}",
                                             index=None, label_visibility="collapsed")
                            val = None
                            if isinstance(c.grandeur, str) and c.grandeur in sl:
                                s = sl[c.grandeur]
                                bornes = " · ".join(x for x in (
                                    f"avertissement hors {s.avert_min:g}–{s.avert_max:g}" if s.avert_min is not None and s.avert_max is not None
                                    else f"avertissement > {s.avert_max:g}" if s.avert_max is not None else "",
                                    f"critique > {s.crit_max:g}" if s.crit_max is not None else "") if x)
                                val = b.number_input(f"{s.libelle} ({s.unite})", value=None, step=0.1, key=f"v_{c.id}",
                                                     help=f"{bornes} — {s.reference}")
                            com = b.text_input("Commentaire", key=f"c_{c.id}", label_visibility="collapsed",
                                               placeholder="Commentaire (facultatif)")
                            with b.expander("📷 Joindre une photo"):
                                ph = st.file_uploader("Photo", type=["jpg", "jpeg", "png"], key=f"p_{c.id}",
                                                      label_visibility="collapsed")
                            saisies.append((c.id, statut, val, com, ph))
                st.markdown("---")
                c1, c2 = st.columns([2, 3])
                insp = c1.text_input("Inspecteur", value=u.get("nom", ""), key="dci_insp")
                obs = c2.text_area("Observations générales", key="dci_obs", height=80)
                cert = st.checkbox("Je certifie l'exactitude des relevés ci-dessus (signature de l'inspecteur)", key="dci_cert")
                envoi = st.form_submit_button("💾 Enregistrer l'inspection", type="primary")
            if envoi:
                remplis = [s for s in saisies if s[1] is not None or s[2] is not None]
                if not insp or not cert:
                    st.error("Indique le nom de l'inspecteur et coche la certification.")
                elif not remplis:
                    st.error("Aucun contrôle renseigné.")
                else:
                    lignes = [{"controle_id": int(cid), "statut": stt, "valeur": None if v is None else float(v),
                               "commentaire": cm or None,
                               "photo_nom": ph.name if ph else None,
                               "photo_b64": base64.b64encode(ph.getvalue()).decode() if ph else None}
                              for cid, stt, v, cm, ph in remplis]
                    iid, bilan = depot.enregistrer_inspection(int(e["id"]), insp,
                                                              None if freq in ("Contrôles dus", "Tous") else freq,
                                                              lignes, obs)
                    st.session_state["_dci_n"] = n + 1
                    st.session_state["_dci_ok"] = {"id": iid, **bilan}
                    st.rerun()
            st.caption("La signature est une empreinte numérique (SHA-256) du nom de l'inspecteur, de l'horodatage et "
                       "des relevés : toute modification ultérieure serait détectable. La signature manuscrite à l'écran "
                       "n'est pas prise en charge dans cette version.")

# ============================================================================= PLAN
with t_plan:
    if plan.empty:
        st.info("Aucun contrôle planifié.")
    else:
        kpi_row([("Contrôles planifiés", str(len(plan)), None),
                 ("En retard ou jamais faits", str(int(plan["en_retard"].sum())), None),
                 ("Équipements avec listes de contrôle", str(plan["code"].nunique()),
                  f"{len(eq) - plan['code'].nunique()} sans liste (à créer)")])
        t = plan.pivot_table(index="code", columns="frequence", values="en_retard", aggfunc=["size", "sum"], fill_value=0)
        res = pd.DataFrame(index=t.index)
        for f in [f for f in modele.FREQUENCES if ("size", f) in t.columns]:
            res[f] = [f"{int(d)} / {int(n)}" for n, d in zip(t[("size", f)], t[("sum", f)])]
        st.caption("Par équipement et par fréquence : contrôles dus / contrôles applicables.")
        st.dataframe(res, width="stretch", height=420)
        sans = eq[~eq["code"].isin(plan["code"])][["code", "designation", "systeme"]]
        if len(sans):
            st.markdown("**Équipements sans liste de contrôle** (à créer à partir des recommandations constructeur)")
            st.dataframe(sans, hide_index=True, width="stretch")

# ============================================================================= HISTORIQUE
with t_hist:
    ins = depot.inspections()
    if ins.empty:
        st.info("Aucune inspection enregistrée.")
    else:
        codes = dict(zip(eq["id"], eq["code"]))
        c1, c2, c3 = st.columns(3)
        d0 = c1.date_input("Depuis", value=(auj - timedelta(days=30)).date(), key="dch_d0", format="DD/MM/YYYY")
        fe = c2.multiselect("Équipement", sorted(set(ins["equipement_id"].map(codes))), key="dch_e")
        fsv = c3.multiselect("Sévérité", ["OK", "Avertissement", "Critique"], key="dch_s")
        r = rel[pd.to_datetime(rel["date"]) >= pd.Timestamp(d0)].assign(Équipement=lambda d: d["equipement_id"].map(codes))
        if fe:
            r = r[r["Équipement"].isin(fe)]
        if fsv:
            r = r[r["severite"].isin(fsv)]
        st.caption(f"{r['inspection_id'].nunique()} inspection(s), {len(r)} relevé(s).")
        vue = r.sort_values(["date", "id"], ascending=False)[[
            "date", "Équipement", "phase", "point", "statut", "valeur", "severite", "commentaire", "inspecteur", "photo_nom"]]
        st.dataframe(vue.rename(columns={"date": "Date", "phase": "Phase", "point": "Contrôle", "statut": "Statut",
                                         "valeur": "Valeur", "severite": "Sévérité", "commentaire": "Commentaire",
                                         "inspecteur": "Inspecteur", "photo_nom": "Photo"})
                     .style.map(colorer_severite, subset=["Sévérité"]), hide_index=True, width="stretch", height=420,
                     column_config={"Date": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm")})
        avec_photo = r[r["photo_nom"].notna()]
        if len(avec_photo):
            lab = {f"{x.Équipement} — {x.point} ({pd.Timestamp(x.date):%d/%m/%Y})": x.id for x in avec_photo.itertuples()}
            ch = st.selectbox("Voir une photo", list(lab), index=None, key="dch_ph")
            if ch:
                nom, b64 = depot.photo(int(lab[ch]))
                st.image(base64.b64decode(b64), caption=nom, width=420)
        buf = io.BytesIO()
        vue.to_excel(buf, index=False)
        st.download_button("⬇️ Exporter (Excel)", buf.getvalue(), "inspections_data_center.xlsx", key="dch_dl")
        with st.expander("Signatures des inspections"):
            st.dataframe(ins.assign(Équipement=ins["equipement_id"].map(codes))[
                ["id", "date", "Équipement", "inspecteur", "signature", "observations"]], hide_index=True, width="stretch")

render_sidebar_footer("")
