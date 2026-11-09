"""Thème (version intégrée à strategieAER, palette claire) — et composants d'interface — « panneau de supervision » dark/néon.

Refonte visuelle validée avec l'utilisateur, **scopée à cette application
seule** (AER_METERDASHBOARD) : le reste de la suite AER Streamlit garde la
palette claire (navy/bleu/or) du tableau de bord Excel — cette application a
désormais sa propre identité visuelle, volontairement différente.

Direction retenue (validée) : compromis « néon réservé aux états ». La
pratique professionnelle des interfaces de supervision industrielle
(philosophie ISA-101 « high-performance HMI ») recommande une base très
majoritairement neutre et réserve la couleur saturée aux états anormaux —
à l'opposé d'un néon généralisé, entre autres parce qu'environ 8 % des
hommes ont une déficience de la vision des couleurs et ne peuvent pas
distinguer de façon fiable deux couleurs qui ne se distinguent QUE par la
teinte. Le compromis adopté ici : la base reste sombre et neutre sur
l'essentiel de la surface, le néon devient un signal réservé aux statuts
(actif / alerte / erreur / info / neutre) — jamais un décor permanent — et
aucune information n'est codée uniquement par la couleur (icône + libellé
systématiques, cf. WCAG 1.4.1).

Couleurs de statut : reprennent exactement les 5 couleurs du brief utilisateur
(émeraude/ambre/rouge/bleu/gris). Contraste vérifié individuellement au calcul
WCAG contre la surface sombre #1a1a19 (le validateur de la skill dataviz les
avait signalées en échec, mais ce validateur note lui-même que ses seuils de
bande de clarté / plancher de chroma ne s'appliquent qu'à un ensemble
CATÉGORIEL affiché côte à côte — pas à des couleurs de statut utilisées une à
la fois) :
    émeraude #10b981 → 6.87:1   ambre #f59e0b → 8.11:1   rouge #ef4444 → 4.63:1
    bleu #3b82f6 → 4.74:1       gris #71717a → 3.60:1 (seuil "composant" 3:1 —
    ne JAMAIS utiliser ce gris en texte de petite taille, uniquement fond /
    icône / bordure ; tout texte gris passe par INK_MUTED ci-dessous).

Palette catégorielle (graphiques multi-séries — type de compteur, phases) :
vient en revanche de la palette de référence **validée** de la skill
`dataviz` pour l'étape sombre (8 teintes, CVD Delta E ≥ 8.4 adjacent, ≥ 19.3
en vision normale) — jamais les couleurs de statut, qui ne doivent jamais
« se faire passer » pour une série (règle explicite de cette palette)."""
from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components
import plotly.graph_objects as go

PAGE_ICON = "🔌"
APP_TITLE = "Statistiques des compteurs — AER"

# --- Statuts (brief utilisateur, vérifiés WCAG individuellement) -----------
STATUS_OK = "#10b981"        # actif / succès — pulse réservé à cet état
STATUS_WARNING = "#f59e0b"
STATUS_CRITICAL = "#ef4444"
STATUS_INFO = "#3b82f6"
STATUS_NEUTRAL = "#71717a"   # fond/icône/bordure seulement — jamais en texte

STATUS_COLORS = {
    "ok": STATUS_OK, "warning": STATUS_WARNING, "critical": STATUS_CRITICAL,
    "info": STATUS_INFO, "neutral": STATUS_NEUTRAL,
}

# --- Surfaces & encre (chrome sombre, palette de référence dataviz) --------
BG_PAGE = "#FFFFFF"
BG_SURFACE = "#FFFFFF"
BG_PANEL = "#F0FDF4"
INK_PRIMARY = "#111827"
INK_SECONDARY = "#374151"
INK_MUTED = "#6B7280"
GRIDLINE = "#E5E7EB"
BASELINE = "#D1D5DB"
BORDER_HAIRLINE = "rgba(5,46,22,0.12)"

# --- Accents pour graphiques à une seule série (jamais une couleur de statut,
# pour ne pas lui faire porter un double rôle) ------------------------------
ACCENT = "#3987e5"        # ex-NAVY / BLUE : barres à série unique
ACCENT_SOLAR = "#d95926"  # ex-GOLD : mise en avant "solaire"
MUTED_BUCKET = INK_MUTED  # ex-GREY : regroupements "Autres / (hors phase)"

# Alias de compatibilité (code existant important ces noms)
NAVY = ACCENT
BLUE = ACCENT
GOLD = ACCENT_SOLAR
GREY = MUTED_BUCKET

# --- Catégorielle multi-séries, étape sombre (skill dataviz, validée) ------
CATEGORICAL = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]


def inject_component_style():
    """Styles des composants de la page compteurs (badges, cartes, barres), sans toucher
    au fond ni à la barre latérale de l'application principale."""
    st.markdown(
        f"""
        <style>
        :root {{
            --bg-page: {BG_PAGE}; --bg-surface: {BG_SURFACE}; --bg-panel: {BG_PANEL};
            --ink-primary: {INK_PRIMARY}; --ink-secondary: {INK_SECONDARY}; --ink-muted: {INK_MUTED};
            --border: {BORDER_HAIRLINE};
            --status-ok: {STATUS_OK}; --status-warning: {STATUS_WARNING};
            --status-critical: {STATUS_CRITICAL}; --status-info: {STATUS_INFO}; --status-neutral: {STATUS_NEUTRAL};
        }}

        [data-testid="stMetricValue"] {{ font-size: 1.5rem; color: var(--ink-primary); font-variant-numeric: tabular-nums; }}
        [data-testid="stMetricLabel"] {{ font-weight: 600; letter-spacing: .02em; color: var(--ink-secondary); }}

        /* st.info/warning/success/error natifs : sans ce bloc, Streamlit les
           rend dans sa palette claire par défaut (fond pastel, texte sombre)
           — une intrusion "mode clair" détonante sur fond sombre. On les
           ramène au même panneau sombre que le reste de l'interface, avec
           un simple liseré de couleur (même langage visuel que
           `.aer-section-title`) plutôt qu'un fond coloré plein : ces
           messages natifs restent un usage secondaire/explicatif dans
           cette application — le vrai statut passe toujours par
           `status_badge` ci-dessous. */
        [data-testid="stAlertContainer"] {{
            background: var(--bg-panel) !important; border: 1px solid var(--border) !important;
            border-radius: 8px;
        }}
        [data-testid="stAlertContainer"] p, [data-testid="stAlertContainer"] [data-testid="stMarkdownContainer"] {{
            color: var(--ink-primary) !important;
        }}
        [data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]) {{ border-left: 3px solid var(--status-warning); }}
        [data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]) {{ border-left: 3px solid var(--status-critical); }}
        [data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]) {{ border-left: 3px solid var(--status-ok); }}
        [data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]) {{ border-left: 3px solid var(--status-info); }}

        .aer-section-title {{
            background: var(--bg-panel); color: var(--ink-primary); font-weight: 700; font-size: .95rem;
            letter-spacing: .03em; padding: 0.55rem 0.9rem; border-radius: 6px; margin: 0.6rem 0 0.8rem 0;
            border-left: 3px solid var(--status-info);
        }}

        div[data-baseweb="tab-list"] {{ gap: 4px; }}
        button[data-baseweb="tab"] {{ color: var(--ink-secondary); }}
        button[data-baseweb="tab"][aria-selected="true"] {{ color: var(--ink-primary); }}
        div[data-baseweb="tab-highlight"] {{ background-color: var(--status-info) !important; }}

        /* Panneau "verre" — usage sparse (hero uniquement), jamais sur une zone de
           données dense : le glassmorphism dégrade le contraste et coûte en GPU
           (backdrop-filter), déconseillé par la littérature 2025 pour les tableaux
           de bord denses. Dégradation propre si "Réduire la transparence" est actif. */
        .aer-glass {{
            background: linear-gradient(160deg, rgba(57,135,229,0.09), rgba(255,255,255,0.02));
            border: 1px solid var(--border); border-radius: 14px; padding: 1.1rem 1rem;
            backdrop-filter: blur(6px);
        }}
        @supports not (backdrop-filter: blur(1px)) {{ .aer-glass {{ background: var(--bg-panel); }} }}
        @media (prefers-reduced-transparency: reduce) {{ .aer-glass {{ backdrop-filter: none; background: var(--bg-panel); }} }}

        .aer-mini-metric {{ text-align: center; padding: .35rem 0; }}
        .aer-mini-label {{ color: var(--ink-secondary); font-size: .72rem; text-transform: uppercase;
                            letter-spacing: .04em; margin-bottom: .1rem; }}
        .aer-mini-value {{ color: var(--ink-primary); font-size: 1.3rem; font-weight: 700; font-variant-numeric: tabular-nums; }}

        /* Badges de statut — icône + libellé toujours présents : la couleur ne
           porte jamais seule l'information (WCAG 1.4.1). */
        .aer-badge {{
            display: inline-flex; align-items: center; gap: .45rem; padding: .35rem .8rem;
            border-radius: 999px; font-size: .82rem; font-weight: 600; border: 1px solid var(--border);
        }}
        .aer-badge-dot {{ width: 8px; height: 8px; border-radius: 50%; flex: none; }}
        .aer-badge-ok {{ color: var(--status-ok); background: rgba(16,185,129,.10); }}
        .aer-badge-ok .aer-badge-dot {{ background: var(--status-ok); box-shadow: 0 0 8px var(--status-ok); }}
        .aer-badge-warning {{ color: var(--status-warning); background: rgba(245,158,11,.10); }}
        .aer-badge-warning .aer-badge-dot {{ background: var(--status-warning); }}
        .aer-badge-critical {{ color: var(--status-critical); background: rgba(239,68,68,.10); }}
        .aer-badge-critical .aer-badge-dot {{ background: var(--status-critical); }}
        .aer-badge-info {{ color: var(--status-info); background: rgba(59,130,246,.10); }}
        .aer-badge-info .aer-badge-dot {{ background: var(--status-info); }}
        .aer-badge-neutral {{ color: var(--ink-secondary); background: rgba(113,113,122,.12); }}
        .aer-badge-neutral .aer-badge-dot {{ background: var(--status-neutral); }}

        /* Respiration lente — réservée aux états actifs/en cours uniquement
           (jamais un ornement permanent, cf. brief). */
        @keyframes aer-breathe {{
            0%, 100% {{ box-shadow: 0 0 6px currentColor; opacity: .88; }}
            50% {{ box-shadow: 0 0 16px currentColor; opacity: 1; }}
        }}
        .aer-pulse .aer-badge-dot {{ animation: aer-breathe 4.5s ease-in-out infinite; }}
        @media (prefers-reduced-motion: reduce) {{ .aer-pulse .aer-badge-dot {{ animation: none; }} }}

        /* Barres de saturation (compteurs installés vs capacité théorique du
           site). Échelle fixée à 150 % de la capacité — une barre pleine à
           100 % masquerait qu'un site a dépassé sa capacité théorique — avec
           un repère vertical fixe au palier des 100 %. Le dépassement
           (« critical ») est le seul état qui respire ici : c'est la seule
           anomalie réelle de cet indicateur (cf. néon réservé aux états). */
        .aer-satbar-row {{
            display: flex; align-items: center; gap: .6rem; padding: .32rem 0;
        }}
        .aer-satbar-label {{
            flex: 0 0 38%; font-size: .82rem; color: var(--ink-secondary);
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }}
        .aer-satbar-detail {{ color: var(--ink-muted); font-size: .74rem; }}
        .aer-satbar-track {{
            position: relative; flex: 1; height: 10px; background: var(--bg-panel);
            border-radius: 5px; overflow: hidden; border: 1px solid var(--border);
        }}
        .aer-satbar-fill {{
            position: absolute; left: 0; top: 0; height: 100%; border-radius: 5px;
            transition: width .5s ease-out;
        }}
        .aer-satbar-ok {{ background: var(--status-ok); }}
        .aer-satbar-warning {{ background: var(--status-warning); }}
        .aer-satbar-critical {{ background: var(--status-critical); animation: aer-satbar-glow 2.2s ease-in-out infinite; }}
        .aer-satbar-neutral {{ background: var(--ink-muted); }}
        @keyframes aer-satbar-glow {{
            0%, 100% {{ box-shadow: 0 0 5px var(--status-critical); }}
            50% {{ box-shadow: 0 0 13px var(--status-critical); }}
        }}
        @media (prefers-reduced-motion: reduce) {{ .aer-satbar-critical {{ animation: none; box-shadow: 0 0 6px var(--status-critical); }} }}
        .aer-satbar-mark {{
            position: absolute; left: 66.667%; top: -2px; bottom: -2px; width: 2px;
            background: rgba(255,255,255,.4); z-index: 1;
        }}
        .aer-satbar-value {{
            flex: 0 0 52px; text-align: right; font-weight: 700; font-size: .82rem;
            font-variant-numeric: tabular-nums;
        }}

        /* Rail de navigation latérale — remplace les onglets du haut. On
           réutilise st.radio (plutôt que plusieurs st.button) parce que son
           état "sélectionné" est exposé nativement dans le DOM
           (input[type=radio]:checked) : un vrai signal d'état à cibler en
           CSS, pas une approximation. Le radio-point lui-même est masqué
           (::first div dans le label) : il ne reste qu'une pastille
           icône+libellé pleine largeur, mise en évidence quand sélectionnée. */
        .aer-nav-brand {{
            font-weight: 700; font-size: 1.0rem; color: var(--ink-primary);
            padding: .3rem .2rem .9rem .2rem; letter-spacing: .02em;
        }}
        [data-testid="stSidebar"] label[data-testid="stRadioOption"] {{
            display: block; width: 100%; padding: .5rem .7rem; border-radius: 8px;
            margin-bottom: 3px; border-left: 3px solid transparent; transition: background .15s ease;
        }}
        [data-testid="stSidebar"] label[data-testid="stRadioOption"] > div > div:first-child {{
            display: none;
        }}
        [data-testid="stSidebar"] label[data-testid="stRadioOption"] [data-testid="stMarkdownContainer"] p {{
            margin: 0; color: var(--ink-secondary); font-size: .9rem;
        }}
        [data-testid="stSidebar"] label[data-testid="stRadioOption"]:hover {{
            background: rgba(255,255,255,.04);
        }}
        [data-testid="stSidebar"] label[data-testid="stRadioOption"]:has(input:checked) {{
            background: rgba(57,135,229,.16); border-left: 3px solid var(--status-info);
        }}
        [data-testid="stSidebar"] label[data-testid="stRadioOption"]:has(input:checked) [data-testid="stMarkdownContainer"] p {{
            color: var(--ink-primary); font-weight: 700;
        }}

        /* Cartes KPI — accent coloré cyclant sur la palette CATÉGORIELLE
           (identité du chiffre), jamais une couleur de statut : ces cartes
           décrivent une grandeur, pas un état à surveiller. */
        .aer-kpicard {{
            background: var(--bg-panel); border: 1px solid var(--border); border-radius: 12px;
            padding: .85rem 1rem; border-top: 3px solid var(--kpi-accent, var(--status-info));
        }}
        .aer-kpicard-top {{ display: flex; align-items: center; gap: .5rem; margin-bottom: .3rem; }}
        .aer-kpicard-icon {{ font-size: 1.1rem; }}
        .aer-kpicard-label {{
            color: var(--ink-secondary); font-size: .76rem; text-transform: uppercase; letter-spacing: .03em;
        }}
        .aer-kpicard-value {{
            color: var(--ink-primary); font-size: 1.55rem; font-weight: 700; font-variant-numeric: tabular-nums;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def section_title(text: str):
    st.markdown(f'<div class="aer-section-title">{text}</div>', unsafe_allow_html=True)


def kpi_row(items: list[tuple[str, str, str | None]]):
    """items : liste de (label, valeur, delta_ou_None)."""
    cols = st.columns(len(items))
    for col, (label, value, delta) in zip(cols, items):
        with col:
            st.metric(label, value, delta=delta)


def mini_metric(label: str, value):
    st.markdown(
        f'<div class="aer-mini-metric"><div class="aer-mini-label">{label}</div>'
        f'<div class="aer-mini-value">{value}</div></div>',
        unsafe_allow_html=True,
    )


def status_badge(label: str, status: str = "info", pulse: bool = False):
    """Badge icône (point coloré) + libellé — jamais la couleur seule.
    `pulse=True` réservé aux états actifs/en cours (voir docstring module)."""
    classes = f"aer-badge aer-badge-{status}" + (" aer-pulse" if pulse else "")
    st.markdown(f'<span class="{classes}"><span class="aer-badge-dot"></span>{label}</span>', unsafe_allow_html=True)


def saturation_bar(nom: str, taux: float | None, statut: str, detail: str = ""):
    """Une ligne = un site : capacité installée (compteurs) vs capacité
    théorique (puissance ÷ 400 W/compteur). Échelle fixe à 150 % de la
    capacité (repère vertical à 100 %), pour que le dépassement reste
    visible plutôt que de saturer la barre à l'identique d'un site pile à
    l'objectif. Jamais la couleur seule : le pourcentage est toujours
    affiché en toutes lettres à droite (WCAG 1.4.1)."""
    if taux is None:
        pct_affiche, largeur = "n/d", 0.0
    else:
        pct_affiche = f"{taux * 100:.0f} %"
        largeur = min(taux / 1.5, 1.0) * 100
    detail_html = f'<span class="aer-satbar-detail"> · {detail}</span>' if detail else ""
    couleur = STATUS_COLORS.get(statut, STATUS_NEUTRAL)
    st.markdown(
        f"""
        <div class="aer-satbar-row">
          <div class="aer-satbar-label" title="{nom}">{nom}{detail_html}</div>
          <div class="aer-satbar-track">
            <div class="aer-satbar-mark"></div>
            <div class="aer-satbar-fill aer-satbar-{statut}" style="width:{largeur:.1f}%;"></div>
          </div>
          <div class="aer-satbar-value" style="color:{couleur};">{pct_affiche}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def kpi_card(icon: str, label: str, value: str, accent: str = STATUS_INFO):
    """Une carte KPI = icône + libellé + valeur, avec un liseré supérieur
    coloré (accent). `accent` vient en général de `CATEGORICAL` (identité
    du chiffre) — jamais de `STATUS_COLORS` ici, une carte KPI décrit une
    grandeur, pas un état à surveiller (ce rôle reste à `status_badge`)."""
    st.markdown(
        f"""
        <div class="aer-kpicard" style="--kpi-accent: {accent};">
          <div class="aer-kpicard-top">
            <span class="aer-kpicard-icon">{icon}</span>
            <span class="aer-kpicard-label">{label}</span>
          </div>
          <div class="aer-kpicard-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def kpi_card_row(items: list[tuple[str, str, str]], accents: list[str] | None = None):
    """items : liste de (icône, libellé, valeur). `accents` est cyclé sur
    `CATEGORICAL` par défaut si non fourni."""
    palette = accents or CATEGORICAL
    cols = st.columns(len(items))
    for i, (col, (icon, label, value)) in enumerate(zip(cols, items)):
        with col:
            kpi_card(icon, label, value, accent=palette[i % len(palette)])


def gauge_chart(value_pct: float, title: str, key: str = "gauge", height: int = 220) -> go.Figure:
    """Jauge 0-100 % (go.Indicator) — toujours accompagnée du chiffre en
    toutes lettres au centre (jamais la position de l'aiguille seule, cf.
    WCAG 1.4.1). L'arc utilise un dégradé de statut (rouge → ambre → vert)
    pour une lecture d'ensemble instantanée ; seule la valeur réelle décide
    du résultat, l'arc est une aide visuelle secondaire."""
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=round(value_pct, 1),
        number={"suffix": " %", "font": {"size": 34, "color": INK_PRIMARY}},
        gauge={
            "axis": {"range": [0, 100], "tickcolor": INK_MUTED, "tickfont": {"color": INK_MUTED, "size": 10}},
            "bar": {"color": ACCENT, "thickness": .28},
            "bgcolor": BG_SURFACE,
            "borderwidth": 0,
            "steps": [
                {"range": [0, 50], "color": "rgba(239,68,68,.18)"},
                {"range": [50, 80], "color": "rgba(245,158,11,.18)"},
                {"range": [80, 100], "color": "rgba(16,185,129,.18)"},
            ],
        },
        title={"text": title, "font": {"size": 13, "color": INK_SECONDARY}},
    ))
    fig.update_layout(
        height=height, margin=dict(l=35, r=35, t=50, b=10),
        paper_bgcolor="rgba(0,0,0,0)", font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif"),
    )
    return fig


def animated_counter(label: str, value: int, status: str = "info", key: str = "counter", height: int = 120):
    """Compteur central animé (count-up), rendu dans un unique
    `components.v1.html` — seule façon fiable d'exécuter du JS sous
    Streamlit : `st.markdown(unsafe_allow_html=True)` supprime toute balise
    `<script>`/`onclick`, et un `components.v1.html` est un iframe totalement
    isolé du reste de la page (il ne peut ni lire ni écrire son DOM).

    La valeur précédente est conservée dans `st.session_state` (clé
    `_prevval_<key>`) : l'iframe, lui, redémarre entièrement à chaque rerun
    et n'a aucune mémoire du compte précédent — sans ce relais côté Python,
    le compteur repartirait de zéro à chaque interaction.

    Easing `easeOutQuad` (décélération) : une valeur qui "se dépose"
    progressivement, cohérente avec un registre de supervision sérieux —
    à la différence d'une courbe à rebond (ease-out-back), dont l'effet
    ludique serait déplacé ici. Déclenché par IntersectionObserver (le
    compteur ne s'anime qu'une fois visible) ; désactivé si
    `prefers-reduced-motion: reduce`."""
    session_key = f"_prevval_{key}"
    prev = st.session_state.get(session_key, 0)
    st.session_state[session_key] = value
    couleur = STATUS_COLORS.get(status, STATUS_INFO)
    components.html(
        f"""
        <div class="wrap">
          <div class="label">{label}</div>
          <div class="value" id="val-{key}">{prev:,}</div>
        </div>
        <style>
          body {{ margin:0; background:transparent; font-family: system-ui,-apple-system,"Segoe UI",sans-serif; }}
          .wrap {{ text-align:center; }}
          .label {{ color:{INK_SECONDARY}; font-size:.78rem; letter-spacing:.05em; text-transform:uppercase;
                    margin-bottom:.2rem; }}
          .value {{ color:{couleur}; font-size:3rem; font-weight:700; line-height:1.1;
                    font-variant-numeric: tabular-nums; text-shadow: 0 0 20px {couleur}4D; }}
          @media (prefers-reduced-motion: reduce) {{ .value {{ text-shadow:none; }} }}
        </style>
        <script>
          function easeOutQuad(t) {{ return t * (2 - t); }}
          function tween(el, from, to, dur) {{
            if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {{
              el.textContent = to.toLocaleString('fr-FR'); return;
            }}
            const t0 = performance.now();
            function step(now) {{
              const p = Math.min((now - t0) / dur, 1);
              const v = Math.round(from + (to - from) * easeOutQuad(p));
              el.textContent = v.toLocaleString('fr-FR');
              if (p < 1) requestAnimationFrame(step);
            }}
            requestAnimationFrame(step);
          }}
          var el = document.getElementById('val-{key}');
          var obs = new IntersectionObserver(function(entries) {{
            entries.forEach(function(e) {{
              if (e.isIntersecting) {{ tween(el, {prev}, {value}, 900); obs.disconnect(); }}
            }});
          }}, {{ threshold: 0.3 }});
          obs.observe(el);
        </script>
        """,
        height=height,
    )


def flow_diagram(postes: list[tuple[str, int]], nb_localites: int, total: int, key: str = "flow", height: int = 230):
    """Flux animé Postes Holley → Localités → Total.

    Points animés le long des tracés via `stroke-dasharray` / une animation
    CSS de `stroke-dashoffset` (technique Jake Archibald) plutôt que SMIL
    (`<animateMotion>`), dont les performances sont documentées comme
    médiocres sur Chrome/Safari — un détail volontaire issu de la recherche
    préparatoire, pas une évidence du brief. Isolé dans un seul
    `components.v1.html`, pour la même raison d'isolement JS que le compteur
    animé ci-dessus."""
    if not postes:
        return
    max_val = max(v for _, v in postes) or 1
    width = 900
    node_r = 7
    x_src, x_mid, x_dst = 90, width / 2, width - 90
    n = len(postes)
    step = height / (n + 1)
    y_mid = height / 2

    base_paths, flow_paths, node_markup = [], [], []
    for i, (nom, val) in enumerate(postes):
        y = step * (i + 1)
        epaisseur = 1.4 + 3.6 * (val / max_val)
        d = f"M {x_src + node_r} {y} C {x_mid - 80} {y}, {x_mid - 80} {y_mid}, {x_mid} {y_mid}"
        base_paths.append(
            f'<path d="{d}" fill="none" stroke="{INK_MUTED}" stroke-opacity=".3" stroke-width="{epaisseur:.1f}"/>'
        )
        flow_paths.append(
            f'<path class="flow-line" d="{d}" fill="none" stroke="{STATUS_INFO}" stroke-width="2.2" '
            f'stroke-dasharray="3 13" style="animation-duration:{2.2 + i * 0.3:.1f}s"/>'
        )
        node_markup.append(
            f'<circle cx="{x_src}" cy="{y}" r="{node_r}" fill="{BG_SURFACE}" stroke="{STATUS_INFO}" stroke-width="2"/>'
            f'<text x="{x_src - node_r - 6}" y="{y + 4}" text-anchor="end" fill="{INK_SECONDARY}" font-size="11">{nom}</text>'
            f'<text x="{x_src}" y="{y - node_r - 6}" text-anchor="middle" fill="{INK_PRIMARY}" font-size="11" '
            f'font-weight="600">{val:,}</text>'
        )

    d_out = f"M {x_mid + node_r + 11} {y_mid} L {x_dst - 14} {y_mid}"
    base_paths.append(f'<path d="{d_out}" fill="none" stroke="{STATUS_OK}" stroke-opacity=".35" stroke-width="5"/>')
    flow_paths.append(
        f'<path class="flow-line" d="{d_out}" fill="none" stroke="{STATUS_OK}" stroke-width="3" '
        f'stroke-dasharray="4 16" style="animation-duration:1.3s"/>'
    )

    svg = f"""<svg viewBox="0 0 {width} {height}" width="100%" height="{height}">
      {''.join(base_paths)}
      {''.join(flow_paths)}
      <circle cx="{x_mid}" cy="{y_mid}" r="11" fill="{BG_SURFACE}" stroke="{STATUS_INFO}" stroke-width="2.5"/>
      <text x="{x_mid}" y="{y_mid - 18}" text-anchor="middle" fill="{INK_SECONDARY}" font-size="11">Localités</text>
      <text x="{x_mid}" y="{y_mid + 26}" text-anchor="middle" fill="{INK_PRIMARY}" font-size="11" font-weight="600">{nb_localites}</text>
      <circle cx="{x_dst}" cy="{y_mid}" r="14" fill="{BG_SURFACE}" stroke="{STATUS_OK}" stroke-width="3"/>
      <text x="{x_dst}" y="{y_mid - 22}" text-anchor="middle" fill="{INK_SECONDARY}" font-size="11">Total</text>
      <text x="{x_dst}" y="{y_mid + 5}" text-anchor="middle" fill="{STATUS_OK}" font-size="14" font-weight="700">{total:,}</text>
      {''.join(node_markup)}
    </svg>"""

    components.html(
        f"""
        <div>{svg}</div>
        <style>
          body {{ margin:0; background:transparent; }}
          @keyframes flow-dash {{ to {{ stroke-dashoffset: -200; }} }}
          .flow-line {{ animation-name: flow-dash; animation-timing-function: linear; animation-iteration-count: infinite; }}
          @media (prefers-reduced-motion: reduce) {{ .flow-line {{ animation: none; opacity: 0; }} }}
        </style>
        """,
        height=height + 12,
    )


def plotly_base_layout(fig: go.Figure, height: int = 380, legend: bool = True) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=48, b=10),
        font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif", size=13, color=INK_SECONDARY),
        title_font=dict(size=15, color=INK_PRIMARY),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(color=INK_SECONDARY)),
        hoverlabel=dict(bgcolor=BG_PANEL, font_size=12, font_color=INK_PRIMARY, bordercolor=BORDER_HAIRLINE),
    )
    # automargin=True : indispensable pour l'export PNG statique (rapport PDF) —
    # contrairement au rendu interactif dans le navigateur, qui agrandit déjà la
    # marge pour les libellés d'axe, le rendu statique kaleido respecte la marge
    # fixe telle quelle et tronque les libellés sans ce réglage (repéré en
    # vérifiant le PDF généré, où les noms de localités se chevauchaient).
    fig.update_xaxes(showgrid=False, zeroline=False, color=INK_MUTED, linecolor=BASELINE, automargin=True)
    fig.update_yaxes(showgrid=True, gridcolor=GRIDLINE, zeroline=False, color=INK_MUTED, linecolor=BASELINE, automargin=True)
    return fig


def render_sidebar_footer():
    st.sidebar.markdown("---")
    st.sidebar.caption("AER · Statistiques des compteurs — panneau de supervision, construit avec Streamlit & Plotly.")
