"""Éléments d'interface communs aux pages du module Data Center : droits, couleurs, en-tête."""
from __future__ import annotations

import streamlit as st

from utils.auth import auth_desactivee, role

ROLES_LECTURE = {"admin", "direction", "sdmse", "technicien", "lecteur"}
ROLES_INSPECTION = {"admin", "direction", "sdmse", "technicien"}
ROLES_GESTION = {"admin", "sdmse"}          # registre, seuils, listes de contrôle
ROLES_SENSIBLE = {"admin", "sdmse"}         # adressage IP, constats de sécurité

COULEURS = {"OK": "#16A34A", "Information": "#2563EB", "Avertissement": "#D97706", "Critique": "#DC2626", "—": "#9CA3AF"}
ICONES = {"OK": "🟢", "Information": "🔵", "Avertissement": "🟠", "Critique": "🔴", "—": "⚪"}


def peut(roles: set[str]) -> bool:
    return auth_desactivee() or role() in roles


def exiger_lecture() -> None:
    if not peut(ROLES_LECTURE):
        st.warning("🔒 Votre profil ne donne pas accès au module Data Center.")
        st.stop()


@st.cache_resource(show_spinner=False)
def _init(url: str, version: str) -> dict:
    from . import depot
    depot._INIT_FAIT.discard(url)
    return depot.initialiser()


def initialiser() -> None:
    """Crée les tables, ajoute les colonnes manquantes et complète le contenu initial : une fois par processus
    et par version du schéma (VERSION_SCHEMA), donc aussi après une mise à jour du code sans redémarrage."""
    from . import depot
    from .modele import VERSION_SCHEMA
    _init(str(depot.moteur().url), VERSION_SCHEMA)


def style() -> None:
    st.markdown("""<style>
.dc-bandeau{background:linear-gradient(90deg,#0F172A,#1F3864);color:#fff;border-radius:14px;padding:.9rem 1.2rem;margin-bottom:.8rem}
.dc-bandeau h2{color:#fff;margin:0;font-size:1.35rem}.dc-bandeau p{margin:.15rem 0 0 0;opacity:.85;font-size:.88rem}
.dc-sys{border-radius:12px;padding:.7rem .8rem;color:#fff;min-height:104px}
.dc-sys b{display:block;font-size:.95rem}.dc-sys span{font-size:.8rem;opacity:.95}
.dc-badge{display:inline-block;border-radius:10px;padding:0 .5rem;color:#fff;font-size:.78rem;font-weight:600}
</style>""", unsafe_allow_html=True)


def bandeau(titre: str, sous_titre: str) -> None:
    st.markdown(f"<div class='dc-bandeau'><h2>{titre}</h2><p>{sous_titre}</p></div>", unsafe_allow_html=True)


def badge(sev: str) -> str:
    return f"<span class='dc-badge' style='background:{COULEURS.get(sev, '#9CA3AF')}'>{sev}</span>"


def colorer_severite(v):
    c = COULEURS.get(v)
    return f"background-color:{c};color:white;font-weight:600" if c and v != "—" else ""


COULEURS_SYSTEME = {"Alimentation électrique": "#F59E0B", "Refroidissement": "#38BDF8", "Réseau": "#22C55E",
                    "Serveurs et stockage": "#6366F1", "Supervision": "#A855F7", "Environnement": "#64748B",
                    "Détection et extinction incendie": "#EF4444", "Sécurité physique": "#0EA5E9"}


def html_baie(nom: str, titre: str, eq, ecarts_par_eq: dict, hauteur: int = 42, px_u: int = 15) -> str:
    """Élévation d'une baie (U1 en bas) : un bloc par équipement, coloré par système, bordé selon l'écart ouvert."""
    import html
    g = eq[(eq["baie"] == nom) & eq["u_debut"].notna() & eq["u_fin"].notna()]
    occ = {}
    for r in g.itertuples():
        for u in range(int(r.u_debut), int(r.u_fin) + 1):
            occ[u] = r
    lignes, u = [], hauteur
    while u >= 1:
        r = occ.get(u)
        if r is None:
            lignes.append(f"<div class='u vide' style='height:{px_u}px'><span>{u}</span></div>")
            u -= 1
            continue
        n = int(r.u_fin) - int(r.u_debut) + 1
        sev = ecarts_par_eq.get(r.id, "OK")
        bord = COULEURS.get(sev) if sev != "OK" else "rgba(0,0,0,.15)"
        etat = "" if r.etat in ("En service", None) else f" · {r.etat}"
        lignes.append(
            f"<div class='u eq' title='{html.escape(r.designation)} — U{int(r.u_debut)}–U{int(r.u_fin)}{etat}' "
            f"style='height:{n * px_u}px;background:{COULEURS_SYSTEME.get(r.systeme, '#94A3B8')};"
            f"border:{3 if sev != 'OK' else 1}px solid {bord}'><span>{int(r.u_fin)}</span>"
            f"<b>{ICONES.get(sev, '') + ' ' if sev != 'OK' else ''}{html.escape(r.code)}</b></div>")
        u = int(r.u_debut) - 1
    return (f"<div class='baie'><div class='bt'>{nom}<small>{html.escape(titre)}</small></div>{''.join(lignes)}"
            f"<div class='bp'>{len(g)} équipement(s) · {len(occ)} U / {hauteur} U</div></div>")


STYLE_BAIES = """<style>
.baies{display:flex;gap:18px;flex-wrap:wrap}
.baie{width:300px;background:#1E293B;border-radius:8px;padding:6px;font-size:11px}
.baie .bt{color:#fff;font-weight:700;text-align:center;font-size:14px;margin-bottom:4px}
.baie .bt small{display:block;font-weight:400;font-size:10px;opacity:.8}
.baie .bp{color:#CBD5E1;text-align:center;margin-top:4px;font-size:10px}
.baie .u{position:relative;box-sizing:border-box;border-radius:3px;margin-bottom:1px;display:flex;align-items:center;justify-content:center}
.baie .vide{background:#334155;opacity:.55}
.baie .u span{position:absolute;left:4px;color:#E2E8F0;font-size:9px}
.baie .eq b{color:#fff;font-size:11px;text-shadow:0 1px 1px rgba(0,0,0,.4);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:230px}
.leg{display:flex;flex-wrap:wrap;gap:10px;font-size:12px;margin:6px 0 10px 0}.leg i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:4px;vertical-align:middle}
</style>"""


def legende_systemes() -> str:
    return "<div class='leg'>" + "".join(f"<span><i style='background:{c}'></i>{s}</span>"
                                          for s, c in COULEURS_SYSTEME.items()) + "</div>"
