from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from utils.data import NAVY, BLUE, GOLD, RED, GREEN, AMBER, CATEGORICAL
from utils.ui import (
    PAGE_ICON, inject_base_style, section_title, plotly_base_layout, kpi_row, gauge_indicator,
    render_sidebar_footer,
)
from utils.loader import get_data
from utils.personnel import get_effective_roster
from utils.vehicules import (
    ENTITES_PARC, EQUIPE_NON_AFFECTEE, CHAUFFEUR_NON_DEFINI, TYPES_VEHICULE_OPTIONS, TYPE_NON_RENSEIGNE,
    STATUTS_OPERATIONNELS, TYPES_EVENEMENT, REGISTER_COLUMNS, JOURNAL_COLUMNS,
    SEUIL_AGE_REFORME_DEFAUT_ANS, RESERVE_APPRO_COORDINATION,
    get_register, set_register, next_vehicule_id, equipe_options,
    get_journal, set_journal, with_age_and_reforme, journal_summary, besoins_par_equipe,
    chauffeurs_disponibles, doublons_chauffeurs, chauffeurs_hors_antenne,
    besoins_acquisition_par_equipe, vehicules_non_affectes_disponibles, besoin_acquisition_global,
)

st.set_page_config(page_title="Parc automobile — AER", page_icon=PAGE_ICON, layout="wide")
inject_base_style()


def _display_df(df: pd.DataFrame, numeric_cols: tuple = (), date_cols: tuple = ()) -> pd.DataFrame:
    """Copie d'affichage (tableaux en lecture seule uniquement) : les valeurs
    manquantes (NaN / NaT) sont affichées en blanc plutôt que comme le texte
    littéral « None » — un rendu par défaut de cette version de Streamlit
    pour les colonnes numériques et date."""
    out = df.copy()
    for c in numeric_cols:
        if c in out.columns:
            out[c] = out[c].apply(lambda v: "" if pd.isna(v) else (f"{v:g}" if isinstance(v, float) else v))
    for c in date_cols:
        if c in out.columns:
            out[c] = pd.to_datetime(out[c], errors="coerce").dt.strftime("%Y-%m-%d").fillna("")
    return out

data = get_data()
if data is None:
    st.stop()

st.title("🚗 Gestion logistique du parc automobile — DGOER")
st.caption("Registre des véhicules, affectation aux antennes/équipes, suivi d'utilisation "
           "(carburant, vidanges, chauffeurs) et échéances de réforme.")

with st.expander("ℹ️ Ce que cette page représente exactement — à lire avant de l'utiliser", expanded=False):
    st.markdown(
        """
**Ce qui est réel ici :** les **12 véhicules** du fichier « gestionnaire du parc auto DGOER » fourni
(Direction/siège — y compris sa sous-rubrique « Maîtrise d'œuvre publique » — + 4 antennes), avec leurs
plaques, marques et années de mise en service recopiées telles quelles : les **4 plaques incomplètes**
(préfixe « CE » seul dans le fichier source) et les **3 années de mise en service manquantes** n'ont pas
été complétées ou devinées.

**Un point d'attention sur les données :** le fichier parc auto classe les véhicules en **5 entités**
(Direction/siège, Nord/Extrême-Nord/Adamaoua, Akonolinga, Nord-Ouest, Limbé), alors que la feuille RH
« Équipes terrain » utilise **9 antennes** différentes et plus fines — les deux listes ne se recouvrent pas
exactement. Le champ **« Entité propriétaire »** reste donc fidèle au fichier parc auto ; le champ
**« Équipe affectée »** est une affectation **optionnelle et distincte**, vers la vraie liste des antennes RH,
pour le suivi logistique fin par équipe.

**Affectation dynamique (onglet « Affectation »)** : le formulaire d'affectation ne propose jamais un nom de
chauffeur libre — seulement les agents **réels** de l'antenne choisie (rôle Chauffeur, statut OK dans la
feuille RH) qui ne conduisent pas déjà un autre véhicule. Trois règles sont appliquées : un véhicule n'a
qu'une seule équipe affectée à la fois, qu'un seul chauffeur à la fois, et un même chauffeur ne peut être
responsable que d'un seul véhicule à la fois. Une édition directe du tableau du registre reste possible mais
n'est pas bloquée par ces règles — la page le signale alors explicitement plutôt que de corriger en silence.

**Besoin d'acquisition (onglet « Statistiques & réforme »)** : logique en deux volets, fixée par
l'utilisateur. **(1)** un chauffeur réel = un véhicule dédié, calculé antenne par antenne : besoin = max(0,
nombre de chauffeurs réels de la feuille RH (rôle Chauffeur, statut OK) − nombre de véhicules qui lui sont
affectés et encore physiquement dans le parc) — en rapprochement direct avec la répartition des équipes de
terrain. **(2)** + une réserve fixe de 2 véhicules pour l'approvisionnement des sites et la coordination
entre antennes, une seule fois pour **toute la structure** (pas démultipliée par antenne). Les véhicules
« non affectés » mais toujours dans le parc sont comptés à part comme un vivier mobilisable par
redéploiement, avant tout achat (« besoin net » ≤ « besoin brut »). Aucun autre critère (kilométrage, usage
partagé, budget) n'entre dans ce calcul, faute de règle officielle communiquée.

**Ce que cette page n'est PAS :**
- Le type de véhicule, la date d'acquisition précise, le chauffeur attitré, le statut opérationnel et le
  journal d'utilisation ne figurent dans **aucun classeur** : ils forment un registre à compléter, pas une
  donnée déjà connue.
- La **date de réforme** est une **estimation**, calculée à partir d'un **seuil d'âge réglable** (7 ans par
  défaut ci-dessous) — aucune règle officielle de réforme (ni kilométrage, ni durée de vie standard) ne
  m'a été communiquée. Elle reste éditable véhicule par véhicule dans le registre si la réalité diffère.
- Comme pour le Suivi de projets et le Fonds revolving, Streamlit ne conserve rien entre deux sessions :
  **téléchargez le registre et le journal en CSV avant de fermer**, et rechargez-les à l'ouverture suivante.
        """
    )

equipes, _unassigned_effectif = get_effective_roster(data.equipes_rows, data.unassigned)
opts_equipes = equipe_options(equipes)

tab_registre, tab_affectation, tab_usage, tab_stats = st.tabs(
    ["🚗 Registre des véhicules", "📍 Affectation", "⛽ Utilisation & chauffeurs", "📊 Statistiques & réforme"]
)

# =====================================================================
# Onglet 1 — Registre des véhicules
# =====================================================================
with tab_registre:
    section_title("➕ AJOUTER UN VÉHICULE AU REGISTRE")
    with st.container(border=True):
        a1, a2, a3 = st.columns(3)
        n_entite = a1.selectbox("Entité propriétaire", ENTITES_PARC, key="veh_add_entite")
        n_plaque = a2.text_input("N° de plaque d'immatriculation", key="veh_add_plaque")
        n_marque = a3.text_input("Marque / Modèle", key="veh_add_marque")

        b1, b2, b3 = st.columns(3)
        n_type = b1.selectbox("Type de véhicule", TYPES_VEHICULE_OPTIONS, key="veh_add_type")
        n_annee = b2.number_input("Année de mise en service", min_value=1990, max_value=date.today().year,
                                   value=date.today().year, step=1, key="veh_add_annee")
        n_statut = b3.selectbox("Statut opérationnel", STATUTS_OPERATIONNELS, key="veh_add_statut")

        c1, c2 = st.columns(2)
        n_equipe = c1.selectbox("Équipe affectée (optionnel)", opts_equipes, key="veh_add_equipe")
        if n_equipe == EQUIPE_NON_AFFECTEE:
            c2.selectbox("Chauffeur responsable", [CHAUFFEUR_NON_DEFINI], disabled=True, key="veh_add_chauffeur_disabled",
                         help="Choisissez d'abord une équipe affectée pour voir ses chauffeurs réels.")
            n_chauffeur = None
        else:
            dispo, pris = chauffeurs_disponibles(n_equipe, equipes, get_register())
            options_chauffeur = [CHAUFFEUR_NON_DEFINI] + dispo
            n_chauffeur = c2.selectbox(
                f"Chauffeur responsable — agents réels de « {n_equipe} »",
                options_chauffeur, key="veh_add_chauffeur",
                help="Liste limitée aux agents RH réels (rôle Chauffeur, statut OK) de cette antenne, "
                     "qui ne conduisent pas déjà un autre véhicule.",
            )
            if not dispo:
                if pris:
                    st.caption(f"⚠️ Aucun chauffeur disponible dans « {n_equipe} » : "
                               f"{', '.join(f'{c} (déjà sur {v})' for c, v in pris.items())}.")
                else:
                    st.caption(f"⚠️ Aucun chauffeur réel (rôle Chauffeur, statut OK) recensé dans « {n_equipe} » "
                               "selon la feuille RH.")

        if st.button("Ajouter au registre", type="primary", key="veh_add_btn"):
            if not n_plaque.strip():
                st.warning("Indiquez au moins un numéro de plaque avant d'ajouter le véhicule.")
            else:
                reg = get_register()
                date_reforme = pd.Timestamp(year=int(n_annee) + SEUIL_AGE_REFORME_DEFAUT_ANS, month=1, day=1)
                chauffeur_retenu = n_chauffeur if (n_chauffeur and n_chauffeur != CHAUFFEUR_NON_DEFINI) else ""
                new_row = pd.DataFrame([{
                    "ID véhicule": next_vehicule_id(reg),
                    "Entité propriétaire": n_entite,
                    "Rubrique source": "Ajouté manuellement",
                    "Équipe affectée": n_equipe,
                    "N° de plaque": n_plaque.strip(),
                    "Marque": n_marque.strip(),
                    "Type de véhicule": n_type,
                    "Année de mise en service": int(n_annee),
                    "Date d'acquisition (précise)": pd.NaT,
                    "Chauffeur attitré": chauffeur_retenu,
                    "Statut opérationnel": n_statut,
                    "Date de réforme (retenue)": date_reforme,
                    "Notes": "",
                }])
                set_register(pd.concat([reg, new_row], ignore_index=True))
                st.success(f"Véhicule « {n_plaque} » ajouté au registre.")
                st.rerun()

    st.write("")
    with st.expander("📤 Charger un registre existant (CSV)"):
        uploaded_reg = st.file_uploader("Fichier CSV précédemment téléchargé", type=["csv"], key="veh_upload")
        if uploaded_reg is not None:
            try:
                loaded = pd.read_csv(uploaded_reg)
                loaded = loaded.reindex(columns=REGISTER_COLUMNS)
                loaded["Année de mise en service"] = pd.to_numeric(loaded["Année de mise en service"], errors="coerce").astype("Int64")
                loaded["Date d'acquisition (précise)"] = pd.to_datetime(loaded["Date d'acquisition (précise)"], errors="coerce")
                loaded["Date de réforme (retenue)"] = pd.to_datetime(loaded["Date de réforme (retenue)"], errors="coerce")
                if st.button("Remplacer le registre courant par ce fichier", key="veh_replace_btn"):
                    set_register(loaded)
                    st.success(f"{len(loaded)} véhicule(s) chargé(s).")
                    st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Fichier illisible : {exc}")

    st.write("")
    section_title("📋 VÉHICULES DU PARC — MODIFIABLES DIRECTEMENT DANS LE TABLEAU")
    register = get_register()
    edited = st.data_editor(
        register,
        width="stretch",
        hide_index=True,
        num_rows="dynamic",
        height=min(60 + 36 * (len(register) + 1), 520),
        column_config={
            "Entité propriétaire": st.column_config.SelectboxColumn("Entité propriétaire", options=ENTITES_PARC),
            "Équipe affectée": st.column_config.SelectboxColumn("Équipe affectée", options=opts_equipes),
            "Type de véhicule": st.column_config.SelectboxColumn("Type de véhicule", options=TYPES_VEHICULE_OPTIONS),
            "Statut opérationnel": st.column_config.SelectboxColumn("Statut opérationnel", options=STATUTS_OPERATIONNELS),
            "Année de mise en service": st.column_config.NumberColumn("Année de mise en service", format="%d"),
            "Date d'acquisition (précise)": st.column_config.DateColumn("Date d'acquisition (précise)"),
            "Date de réforme (retenue)": st.column_config.DateColumn("Date de réforme (retenue)"),
        },
        key="vehicules_editor",
    )
    set_register(edited)
    register = edited

    st.download_button("⬇️ Télécharger le registre (CSV)",
                        register.to_csv(index=False).encode("utf-8"),
                        f"registre_parc_auto_{date.today().isoformat()}.csv", "text/csv")

# =====================================================================
# Onglet 2 — Affectation
# =====================================================================
with tab_affectation:
    section_title("🧭 AFFECTER / RÉAFFECTER UN VÉHICULE À UNE ANTENNE")
    st.caption("Le chauffeur proposé est toujours un agent RÉEL de l'équipe RH choisie (rôle Chauffeur, statut "
               "OK) qui ne conduit pas déjà un autre véhicule — jamais un nom saisi librement. Un véhicule n'a "
               "qu'une seule équipe affectée et qu'un seul chauffeur à la fois ; un chauffeur ne peut être "
               "responsable que d'un seul véhicule à la fois.")
    register = get_register()
    if register.empty:
        st.info("Aucun véhicule dans le registre pour l'instant — ajoutez-en un dans l'onglet « Registre des "
                "véhicules ».")
    else:
        with st.container(border=True):
            labels, label_to_id = [], {}
            for _, r in register.iterrows():
                base = f"{r['ID véhicule']} — {r['N° de plaque']} ({r['Marque']})"
                if r["Équipe affectée"] != EQUIPE_NON_AFFECTEE:
                    chauf = str(r.get("Chauffeur attitré") or "").strip()
                    base += (f" — déjà affecté : {r['Équipe affectée']}"
                             + (f" (chauffeur : {chauf})" if chauf else " (sans chauffeur désigné)"))
                else:
                    base += " — non affecté"
                labels.append(base)
                label_to_id[base] = r["ID véhicule"]

            aff1, aff2 = st.columns(2)
            label_choisi = aff1.selectbox("Véhicule à affecter / réaffecter", labels, index=None,
                                           placeholder="Choisir un véhicule…", key="aff_vehicule")
            vid_choisi = label_to_id.get(label_choisi) if label_choisi else None
            antenne_choisie = aff2.selectbox("Équipe affectée (antenne)", opts_equipes, key="aff_equipe")

            chauffeur_choisi = None
            if antenne_choisie == EQUIPE_NON_AFFECTEE:
                st.caption("Choisir « (non affecté à une équipe) » retire aussi le chauffeur attitré de ce "
                           "véhicule.")
            else:
                dispo, pris = chauffeurs_disponibles(antenne_choisie, equipes, register, exclude_vehicule_id=vid_choisi)
                options_chauffeur = [CHAUFFEUR_NON_DEFINI] + dispo
                chauffeur_choisi = st.selectbox(
                    f"Chauffeur responsable — agents réels de « {antenne_choisie} »",
                    options_chauffeur, key="aff_chauffeur",
                    help="Liste limitée aux agents RH réels (rôle Chauffeur, statut OK) de cette antenne, "
                         "qui ne conduisent pas déjà un autre véhicule.",
                )
                if not dispo:
                    if pris:
                        detail = ", ".join(f"{c} (déjà sur {v})" for c, v in pris.items())
                        st.caption(f"⚠️ Aucun chauffeur disponible dans « {antenne_choisie} » : {detail}.")
                    else:
                        st.caption(f"⚠️ Aucun chauffeur réel (rôle Chauffeur, statut OK) recensé dans "
                                   f"« {antenne_choisie} » selon la feuille RH.")

            if st.button("Valider l'affectation", type="primary", key="aff_btn"):
                if not vid_choisi:
                    st.warning("Choisissez un véhicule avant de valider.")
                else:
                    reg2 = get_register().copy()
                    idx = reg2.index[reg2["ID véhicule"] == vid_choisi]
                    if len(idx) == 0:
                        st.error("Véhicule introuvable dans le registre (a-t-il été supprimé entre-temps ?).")
                    else:
                        i = idx[0]
                        chauf_retenu = ""
                        conflit = pd.DataFrame()
                        if antenne_choisie != EQUIPE_NON_AFFECTEE and chauffeur_choisi and chauffeur_choisi != CHAUFFEUR_NON_DEFINI:
                            chauf_retenu = chauffeur_choisi
                            conflit = reg2[(reg2["ID véhicule"] != vid_choisi) & (reg2["Chauffeur attitré"] == chauf_retenu)]
                        if chauf_retenu and not conflit.empty:
                            st.error(f"« {chauf_retenu} » est déjà chauffeur du véhicule "
                                     f"{conflit.iloc[0]['ID véhicule']} — choisissez un autre chauffeur.")
                        else:
                            reg2.loc[i, "Équipe affectée"] = antenne_choisie
                            reg2.loc[i, "Chauffeur attitré"] = chauf_retenu
                            set_register(reg2)
                            msg = f"Véhicule {vid_choisi} affecté à « {antenne_choisie} »"
                            msg += f", chauffeur : {chauf_retenu}." if chauf_retenu else " (sans chauffeur désigné)."
                            st.success(msg)
                            st.rerun()

        doublons = doublons_chauffeurs(get_register())
        if doublons:
            detail = " ; ".join(f"{nom} → {', '.join(str(v) for v in vids)}" for nom, vids in doublons.items())
            st.warning(f"⚠️ Incohérence détectée dans le registre (probablement via une édition directe du "
                       f"tableau) : un même chauffeur apparaît sur plusieurs véhicules — {detail}. Corrigez via "
                       f"le formulaire ci-dessus ou directement dans le tableau du registre.")

        hors_antenne = chauffeurs_hors_antenne(get_register(), equipes)
        if hors_antenne:
            detail2 = " ; ".join(f"{h['ID véhicule']} ({h['Équipe affectée']} / {h['Chauffeur attitré']})"
                                  for h in hors_antenne)
            st.warning(f"⚠️ Incohérence détectée : chauffeur attitré qui n'est pas un agent réel (rôle "
                       f"Chauffeur, statut OK) de l'équipe affectée du véhicule — {detail2}. Probablement une "
                       f"équipe changée directement dans le tableau sans mettre à jour le chauffeur.")

    st.write("")
    section_title("📍 RÉPARTITION DU PARC PAR ENTITÉ ET PAR ÉQUIPE")
    register = get_register()
    if register.empty:
        st.info("Aucun véhicule dans le registre pour l'instant.")
    else:
        kpi_row([
            ("Véhicules au total", str(len(register)), None),
            ("Affectés à une équipe", str(int((register["Équipe affectée"] != EQUIPE_NON_AFFECTEE).sum())), None),
            ("Non affectés", str(int((register["Équipe affectée"] == EQUIPE_NON_AFFECTEE).sum())), None),
            ("Entités propriétaires couvertes", str(register["Entité propriétaire"].nunique()), None),
        ])

        fc1, fc2, fc3 = st.columns(3)
        f_entite = fc1.multiselect("Filtrer par entité propriétaire", ENTITES_PARC, default=[])
        f_equipe = fc2.multiselect("Filtrer par équipe affectée", opts_equipes, default=[])
        f_statut = fc3.multiselect("Filtrer par statut opérationnel", STATUTS_OPERATIONNELS, default=[])

        view = register.copy()
        if f_entite:
            view = view[view["Entité propriétaire"].isin(f_entite)]
        if f_equipe:
            view = view[view["Équipe affectée"].isin(f_equipe)]
        if f_statut:
            view = view[view["Statut opérationnel"].isin(f_statut)]

        cols_show = ["ID véhicule", "Entité propriétaire", "Équipe affectée", "N° de plaque", "Marque",
                     "Type de véhicule", "Statut opérationnel", "Chauffeur attitré"]
        st.dataframe(view[cols_show], width="stretch", hide_index=True, height=360)

        st.write("")
        g1, g2 = st.columns(2)
        with g1:
            by_entite = register.groupby("Entité propriétaire", as_index=False).size()
            fig = px.bar(by_entite.sort_values("size", ascending=False), x="Entité propriétaire", y="size",
                         color_discrete_sequence=[BLUE], title="Véhicules par entité propriétaire")
            fig = plotly_base_layout(fig, legend=False)
            fig.update_layout(yaxis_title="Véhicules", xaxis_title="")
            st.plotly_chart(fig, width="stretch")
        with g2:
            by_equipe = register[register["Équipe affectée"] != EQUIPE_NON_AFFECTEE].groupby(
                "Équipe affectée", as_index=False).size()
            if by_equipe.empty:
                st.info("Aucun véhicule encore affecté à une équipe précise — tous restent en "
                        "« non affecté » ou au niveau de l'entité propriétaire seule.")
            else:
                fig = px.bar(by_equipe.sort_values("size", ascending=False), x="Équipe affectée", y="size",
                             color_discrete_sequence=[GOLD], title="Véhicules par équipe affectée (RH)")
                fig = plotly_base_layout(fig, legend=False)
                fig.update_layout(yaxis_title="Véhicules", xaxis_title="")
                st.plotly_chart(fig, width="stretch")

        st.write("")
        section_title("🧭 COUVERTURE PAR ANTENNE RH — REPÈRE, PAS UNE DOTATION OFFICIELLE")
        st.caption("Simple indicateur de couverture (antenne RH sans aucun véhicule affecté) — aucun ratio "
                   "véhicules/agents officiel ne figure dans les classeurs disponibles.")
        besoins = besoins_par_equipe(register, equipes)
        if besoins.empty:
            st.info("Feuille « Données - Équipes » indisponible : impossible de calculer la couverture par antenne.")
        else:
            st.dataframe(besoins, width="stretch", hide_index=True, height=360)

# =====================================================================
# Onglet 3 — Utilisation & chauffeurs
# =====================================================================
with tab_usage:
    section_title("➕ ENREGISTRER UN ÉVÉNEMENT D'UTILISATION")
    register = get_register()
    if register.empty:
        st.info("Ajoutez d'abord au moins un véhicule dans l'onglet « Registre des véhicules ».")
    else:
        with st.container(border=True):
            vehicule_labels = (register["ID véhicule"] + " — " + register["N° de plaque"].fillna("")
                                + " (" + register["Marque"].fillna("") + ")")
            label_to_id = dict(zip(vehicule_labels, register["ID véhicule"]))
            u1, u2, u3 = st.columns(3)
            u_label = u1.selectbox("Véhicule", vehicule_labels, index=None, placeholder="Choisir un véhicule…",
                                    key="usage_add_vehicule")
            u_date = u2.date_input("Date", value=date.today(), key="usage_add_date")
            u_type = u3.selectbox("Type d'événement", TYPES_EVENEMENT, key="usage_add_type")

            v1, v2, v3 = st.columns(3)
            u_carburant = v1.number_input("Quantité carburant (L)", min_value=0.0, step=1.0, value=0.0,
                                           key="usage_add_carburant")
            u_km = v2.number_input("Kilométrage au compteur (km)", min_value=0.0, step=1.0, value=0.0,
                                    key="usage_add_km")
            u_cout = v3.number_input("Coût (FCFA)", min_value=0.0, step=1000.0, value=0.0, key="usage_add_cout")

            w1, w2 = st.columns(2)
            default_chauffeur = ""
            if u_label and u_label in label_to_id:
                row = register[register["ID véhicule"] == label_to_id[u_label]].iloc[0]
                default_chauffeur = row.get("Chauffeur attitré", "") or ""
            u_chauffeur = w1.text_input("Chauffeur", value=default_chauffeur, key="usage_add_chauffeur")
            u_notes = w2.text_input("Notes", key="usage_add_notes")

            if st.button("Enregistrer l'événement", type="primary", key="usage_add_btn"):
                if not u_label:
                    st.warning("Choisissez un véhicule avant d'enregistrer l'événement.")
                else:
                    journal = get_journal()
                    new_event = pd.DataFrame([{
                        "ID véhicule": label_to_id[u_label],
                        "Date": pd.to_datetime(u_date),
                        "Type d'événement": u_type,
                        "Quantité carburant (L)": u_carburant if u_carburant > 0 else float("nan"),
                        "Kilométrage au compteur (km)": u_km if u_km > 0 else float("nan"),
                        "Coût (FCFA)": u_cout if u_cout > 0 else float("nan"),
                        "Chauffeur": u_chauffeur.strip(),
                        "Notes": u_notes.strip(),
                    }])
                    combined = pd.concat([journal, new_event], ignore_index=True)
                    for c in ["Quantité carburant (L)", "Kilométrage au compteur (km)", "Coût (FCFA)"]:
                        combined[c] = pd.to_numeric(combined[c], errors="coerce")
                    set_journal(combined)
                    st.success("Événement enregistré dans le journal d'utilisation.")
                    st.rerun()

    st.write("")
    with st.expander("📤 Charger un journal d'utilisation existant (CSV)"):
        uploaded_jr = st.file_uploader("Fichier CSV précédemment téléchargé", type=["csv"], key="usage_upload")
        if uploaded_jr is not None:
            try:
                loaded_j = pd.read_csv(uploaded_jr)
                loaded_j = loaded_j.reindex(columns=JOURNAL_COLUMNS)
                loaded_j["Date"] = pd.to_datetime(loaded_j["Date"], errors="coerce")
                if st.button("Remplacer le journal courant par ce fichier", key="usage_replace_btn"):
                    set_journal(loaded_j)
                    st.success(f"{len(loaded_j)} événement(s) chargé(s).")
                    st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Fichier illisible : {exc}")

    st.write("")
    section_title("📒 JOURNAL D'UTILISATION — MODIFIABLE DIRECTEMENT DANS LE TABLEAU")
    journal = get_journal()
    if journal.empty:
        st.info("Aucun événement saisi pour l'instant. Utilisez le formulaire ci-dessus, ou chargez un journal "
                "CSV précédemment téléchargé.")
    else:
        edited_j = st.data_editor(
            journal,
            width="stretch",
            hide_index=True,
            num_rows="dynamic",
            height=min(60 + 36 * (len(journal) + 1), 420),
            column_config={
                "Date": st.column_config.DateColumn("Date"),
                "Type d'événement": st.column_config.SelectboxColumn("Type d'événement", options=TYPES_EVENEMENT),
            },
            key="journal_editor",
        )
        set_journal(edited_j)
        journal = edited_j

        st.download_button("⬇️ Télécharger le journal (CSV)",
                            journal.to_csv(index=False).encode("utf-8"),
                            f"journal_utilisation_parc_auto_{date.today().isoformat()}.csv", "text/csv",
                            key="usage_dl_journal")

        st.write("")
        section_title("🚘 SYNTHÈSE PAR VÉHICULE — CALCULÉE À PARTIR DU JOURNAL SAISI")
        summary = journal_summary(journal)
        if summary.empty:
            st.info("Aucun événement exploitable pour l'instant.")
        else:
            merged = summary.merge(
                register[["ID véhicule", "N° de plaque", "Marque", "Équipe affectée"]],
                on="ID véhicule", how="left"
            )
            cols_order = ["ID véhicule", "N° de plaque", "Marque", "Équipe affectée", "Carburant total (L)",
                          "Coût total (FCFA)", "Nb vidanges", "Dernière vidange", "Dernier kilométrage relevé"]
            merged_disp = _display_df(
                merged[cols_order],
                numeric_cols=("Carburant total (L)", "Coût total (FCFA)", "Nb vidanges", "Dernier kilométrage relevé"),
                date_cols=("Dernière vidange",),
            )
            st.dataframe(merged_disp, width="stretch", hide_index=True, height=320)

# =====================================================================
# Onglet 4 — Statistiques & réforme
# =====================================================================
with tab_stats:
    register = get_register()
    if register.empty:
        st.info("Ajoutez d'abord au moins un véhicule dans l'onglet « Registre des véhicules ».")
    else:
        section_title("⚙️ PARAMÈTRE DE RÉFORME — SEUIL D'ÂGE (AUCUNE RÈGLE OFFICIELLE COMMUNIQUÉE)")
        seuil = st.slider("Seuil d'âge de réforme suggéré (ans)", min_value=3, max_value=15,
                           value=SEUIL_AGE_REFORME_DEFAUT_ANS, key="veh_seuil_reforme")
        st.caption("Ce seuil ne sert qu'à calculer une **suggestion** de date de réforme à partir de l'année de "
                   "mise en service. La colonne « Date de réforme (retenue) » du registre, si elle est renseignée "
                   "manuellement, prime toujours sur cette suggestion.")

        view = with_age_and_reforme(register, seuil)

        st.write("")
        n_alerte = int((view["Statut réforme"] == "À surveiller (≤ 12 mois)").sum())
        n_depasse = int((view["Statut réforme"] == "Échéance dépassée").sum())
        n_inconnu = int((view["Statut réforme"] == "Non calculable (année inconnue)").sum())
        age_moyen = view["Âge (ans)"].dropna()
        kpi_row([
            ("Véhicules suivis", str(len(view)), None),
            ("Âge moyen (ans)", f"{age_moyen.mean():.1f}" if not age_moyen.empty else "—", None),
            ("Échéance dépassée", str(n_depasse), None),
            ("À surveiller (≤ 12 mois)", str(n_alerte), None),
            ("Année inconnue (non calculable)", str(n_inconnu), None),
        ])

        st.write("")
        section_title("🛒 BESOIN D'ACQUISITION DE VÉHICULES")
        st.caption(
            "Logique adoptée par l'utilisateur, en deux volets : **(1)** chaque chauffeur **réel** (agent RH, "
            "rôle « Chauffeur », statut OK) doit disposer d'un véhicule dédié — calculé antenne par antenne, "
            "en rapprochement avec la répartition des équipes de terrain ; **(2)** + "
            f"**{RESERVE_APPRO_COORDINATION} véhicules de réserve** pour l'approvisionnement des sites et la "
            "coordination entre antennes — une seule fois pour **toute la structure**, pas démultipliés par "
            "antenne. Ce n'est pas une dotation officielle — aucun autre critère (kilométrage, budget "
            "disponible...) n'est pris en compte. Les échéances de réforme ci-dessus viendront s'ajouter à ce "
            "besoin à mesure que des véhicules sortiront du parc."
        )
        glob = besoin_acquisition_global(register, equipes)
        besoins_acq = glob["besoins_par_antenne"]
        if besoins_acq.empty:
            st.info("Feuille « Données - Équipes » indisponible : impossible de calculer le besoin d'acquisition.")
        else:
            gc1, gc2 = st.columns([1, 1.4])
            with gc1:
                fig_gauge = gauge_indicator(
                    glob["taux_couverture"], "Couverture du besoin total par le parc actuel",
                    max_value=100, suffix="%", low_threshold=50, high_threshold=90,
                )
                st.plotly_chart(fig_gauge, width="stretch")
            with gc2:
                kpi_row([
                    ("Chauffeurs réels (toutes antennes)", str(glob["total_chauffeurs"]), None),
                    ("Réserve appro/coordination (fixe)", str(glob["reserve_appro_coordination"]), None),
                    ("Besoin brut total (chauffeurs + réserve)", str(glob["besoin_brut_total"]), None),
                    ("Véhicules non affectés mobilisables", str(glob["pool_non_affecte"]), None),
                ])
                st.metric("Besoin net d'acquisition (estimation)", str(glob["besoin_net_total"]))
            if glob["pool_non_affecte"] > 0 and glob["besoin_brut_total"] > 0:
                st.caption(
                    f"ℹ️ {glob['pool_non_affecte']} véhicule(s) actuellement « non affecté(s) » (et toujours "
                    f"dans le parc) pourrai(en)t couvrir une partie du besoin par simple redéploiement, avant "
                    f"tout achat — d'où le besoin net ci-dessus, inférieur ou égal au besoin brut. Cette page "
                    f"ne décide pas elle-même ce redéploiement : à vous de valider antenne par antenne dans "
                    f"l'onglet « Affectation »."
                )

            st.dataframe(besoins_acq, width="stretch", hide_index=True, height=360)
            st.download_button("⬇️ Télécharger le besoin d'acquisition par antenne (CSV)",
                                besoins_acq.to_csv(index=False).encode("utf-8"),
                                "besoin_acquisition_vehicules.csv", "text/csv", key="veh_dl_besoin_acq")

            besoin_affiche = besoins_acq[besoins_acq["Besoin d'acquisition (1 chauffeur = 1 véhicule)"] > 0]
            if besoin_affiche.empty:
                st.success(f"✅ Aucune antenne n'a de chauffeur réel sans véhicule dédié — il reste la réserve "
                           f"fixe de {RESERVE_APPRO_COORDINATION} véhicule(s) appro/coordination pour toute "
                           f"la structure dans le besoin total ci-dessus.")
            else:
                fig = px.bar(
                    besoin_affiche.sort_values("Besoin d'acquisition (1 chauffeur = 1 véhicule)", ascending=False),
                    x="Antenne (RH)", y="Besoin d'acquisition (1 chauffeur = 1 véhicule)",
                    color_discrete_sequence=[RED], title="Véhicules à acquérir par antenne (hors réserve appro/coordination)",
                )
                fig = plotly_base_layout(fig, legend=False)
                fig.update_layout(yaxis_title="Véhicules à acquérir", xaxis_title="")
                st.plotly_chart(fig, width="stretch")

        g1, g2 = st.columns(2)
        with g1:
            counts = view["Statut opérationnel"].value_counts().reindex(STATUTS_OPERATIONNELS).fillna(0)
            colors_map = {"En service": GREEN, "En panne": AMBER, "En réforme": GOLD,
                          "Réformé / sorti du parc": RED}
            fig = go.Figure(data=[go.Pie(
                labels=counts.index, values=counts.values, hole=0.45,
                marker=dict(colors=[colors_map.get(s, "#8A8A8A") for s in counts.index]),
                textinfo="label+percent", sort=False,
            )])
            fig.update_layout(title="Répartition par statut opérationnel")
            fig = plotly_base_layout(fig, legend=False)
            st.plotly_chart(fig, width="stretch")
        with g2:
            statut_counts = view["Statut réforme"].value_counts()
            colors_reforme = {"OK": GREEN, "À surveiller (≤ 12 mois)": AMBER,
                               "Échéance dépassée": RED, "Non calculable (année inconnue)": "#8A8A8A"}
            labels_courts = {"OK": "OK", "À surveiller (≤ 12 mois)": "À surveiller",
                              "Échéance dépassée": "Dépassée", "Non calculable (année inconnue)": "Année inconnue"}
            fig = go.Figure(data=[go.Pie(
                labels=[labels_courts.get(s, s) for s in statut_counts.index],
                values=statut_counts.values, hole=0.45,
                marker=dict(colors=[colors_reforme.get(s, "#8A8A8A") for s in statut_counts.index]),
                textinfo="label+percent", sort=False,
            )])
            fig.update_layout(title="Répartition par échéance de réforme (estimation)")
            fig = plotly_base_layout(fig, legend=True)
            st.plotly_chart(fig, width="stretch")

        st.write("")
        section_title("🚨 ÉCHÉANCES DE RÉFORME — TRIÉES PAR URGENCE")
        cols_reforme = ["ID véhicule", "N° de plaque", "Marque", "Entité propriétaire", "Équipe affectée",
                         "Année de mise en service", "Âge (ans)", "Date de réforme (retenue ou suggérée)",
                         "Statut réforme"]
        ordre_urgence = {"Échéance dépassée": 0, "À surveiller (≤ 12 mois)": 1, "OK": 2,
                          "Non calculable (année inconnue)": 3}
        view_tri = view.copy()
        view_tri["_ordre"] = view_tri["Statut réforme"].map(ordre_urgence).fillna(9)
        view_tri = view_tri.sort_values(["_ordre", "Date de réforme (retenue ou suggérée)"])
        reforme_disp = _display_df(
            view_tri[cols_reforme],
            numeric_cols=("Année de mise en service", "Âge (ans)"),
            date_cols=("Date de réforme (retenue ou suggérée)",),
        )
        st.dataframe(reforme_disp, width="stretch", hide_index=True, height=380)
        st.download_button("⬇️ Télécharger les échéances de réforme (CSV)",
                            view_tri[cols_reforme].to_csv(index=False).encode("utf-8"),
                            "echeances_reforme_parc_auto.csv", "text/csv", key="veh_dl_reforme")

        st.write("")
        section_title("⛽ CONSOMMATION DE CARBURANT CUMULÉE — D'APRÈS LE JOURNAL SAISI")
        journal = get_journal()
        summary = journal_summary(journal)
        if summary.empty:
            st.info("Aucun événement de carburant saisi pour l'instant dans l'onglet « Utilisation & chauffeurs ».")
        else:
            merged = summary.merge(register[["ID véhicule", "N° de plaque"]], on="ID véhicule", how="left")
            merged = merged.dropna(subset=["Carburant total (L)"])
            if merged.empty:
                st.info("Aucune quantité de carburant renseignée pour l'instant.")
            else:
                fig = px.bar(merged.sort_values("Carburant total (L)", ascending=False),
                             x="N° de plaque", y="Carburant total (L)",
                             color_discrete_sequence=CATEGORICAL, title="Carburant total consommé par véhicule")
                fig = plotly_base_layout(fig, legend=False)
                fig.update_layout(xaxis_title="")
                st.plotly_chart(fig, width="stretch")

render_sidebar_footer(data.generated_on if data else "")
