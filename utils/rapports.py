"""
Génération automatique du rapport de synthèse (PDF).

Réutilise le générateur PDF générique déjà validé sur l'application
AER_METERDASHBOARD (fpdf2 pour la mise en page, kaleido pour exporter les
graphiques Plotly en image) — même limite connue de police (Helvetica ne
couvre que le latin-1 : `_pdf_safe` neutralise la ponctuation hors-latin-1 et
les emojis plutôt que de faire planter l'export).

Le rapport n'invente aucun chiffre : chaque section relit les données déjà
calculées ailleurs dans l'application (classeur AER, registre de suivi de
projets, registre du Fonds revolving, recommandations du moteur de règles) —
ce module ne fait que les mettre en page.
"""
from __future__ import annotations

import os
import tempfile

import pandas as pd
import plotly.graph_objects as go

_PDF_REMPLACEMENTS = {
    "—": "-", "–": "-", "’": "'", "‘": "'", "“": '"', "”": '"', "…": "...",
    "⟨": "[", "⟩": "]", "œ": "oe", "Œ": "OE", "≥": ">=", "≤": "<=", "→": "->", "€": "EUR", "•": "-",
    "🔶": "*", "🚨": "!", "📌": "", "📄": "", "✅": "", " ": " ",
}


def _pdf_safe(texte) -> str:
    s = str(texte)
    for a, b in _PDF_REMPLACEMENTS.items():
        s = s.replace(a, b)
    return s.encode("latin-1", errors="replace").decode("latin-1")


def _estimate_image_height(image_bytes: bytes, target_width_mm: float) -> float:
    """Hauteur (mm) qu'occupera l'image une fois mise à l'échelle sur
    `target_width_mm` de large — lue depuis les dimensions réelles du PNG,
    jamais une valeur fixe, pour que la vérification de place disponible sur
    la page soit fiable quel que soit le ratio largeur/hauteur du graphique."""
    try:
        from PIL import Image
        import io
        with Image.open(io.BytesIO(image_bytes)) as img:
            w_px, h_px = img.size
        return target_width_mm * (h_px / w_px)
    except Exception:  # noqa: BLE001
        return target_width_mm * (420 / 900)  # repli : ratio par défaut des graphiques de ce module


def _fig_to_png_bytes(fig: go.Figure, width: int = 900, height: int = 420, marge_gauche: int = 55) -> bytes | None:
    """Exporte un graphique Plotly en PNG via kaleido — renvoie None (plutôt
    que de faire échouer tout le rapport) si l'export d'une figure précise
    échoue pour une raison quelconque.

    La marge gauche de `plotly_base_layout` (10px, pensée pour le rendu
    interactif Streamlit) ne laisse pas assez de place aux libellés de l'axe
    des ordonnées une fois exportée en image statique à cette résolution —
    constaté visuellement : un axe affichant uniquement "0" au lieu de "20",
    "40"... (premier chiffre tronqué). On élargit les marges uniquement pour
    l'export PDF, sans toucher au thème partagé (`utils/ui.py`) qui sert
    aussi aux graphiques interactifs des 8 autres pages de l'application."""
    try:
        fig.update_layout(margin=dict(l=marge_gauche, r=20, t=55, b=70))
        return fig.to_image(format="png", width=width, height=height, scale=2)
    except Exception:  # noqa: BLE001
        return None


def _fit(pdf, texte: str, largeur: float) -> str:
    """Tronque le texte (avec « ... ») pour qu'il tienne dans la largeur de cellule."""
    t = _pdf_safe(texte)
    if pdf.get_string_width(t) <= largeur - 2:
        return t
    while t and pdf.get_string_width(t + "...") > largeur - 2:
        t = t[:-1]
    return t + "..."


def build_pdf_report(titre: str, sous_titre: str, genere_le: str,
                      kpis: list[tuple[str, str]], sections: list[dict], libelle_date: str = "Généré le") -> bytes:
    """sections: liste de dicts {"titre": str, "texte": str|None,
    "image_bytes": bytes|None, "tableau": DataFrame|None}."""
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(31, 56, 100)
    pdf.multi_cell(0, 8, _pdf_safe(titre), align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 7, _pdf_safe(sous_titre), ln=True)
    pdf.cell(0, 6, _pdf_safe(f"{libelle_date} {genere_le}"), ln=True)
    pdf.ln(4)

    if kpis:
        col_w = (pdf.w - 2 * pdf.l_margin) / len(kpis)
        y0 = pdf.get_y()
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(31, 56, 100)
        x = pdf.l_margin
        for _, value in kpis:
            pdf.set_xy(x, y0)
            pdf.multi_cell(col_w, 6, _pdf_safe(value), align="C")
            x += col_w
        y_labels = y0 + 8
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(110, 110, 110)
        x = pdf.l_margin
        y_apres_labels = y_labels
        for label, _ in kpis:
            pdf.set_xy(x, y_labels)
            pdf.multi_cell(col_w, 4, _pdf_safe(label), align="C")
            y_apres_labels = max(y_apres_labels, pdf.get_y())
            x += col_w
        pdf.set_y(y_apres_labels)
        pdf.ln(6)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(4)

    for section in sections:
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(31, 56, 100)
        pdf.cell(0, 8, _pdf_safe(section["titre"]), ln=True)
        if section.get("texte"):
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(60, 60, 60)
            # new_x/new_y explicites : par défaut, multi_cell() laisse le curseur
            # en haut-droite de son propre bloc plutôt qu'en bas-gauche — sans ça,
            # l'élément suivant (en-tête de tableau, image) démarrait collé au bord
            # droit de la page, superposé à la fin du texte qui vient d'être écrit
            # (bug constaté visuellement : un en-tête de tableau flottant, détaché
            # de ses propres colonnes).
            pdf.multi_cell(0, 5, _pdf_safe(section["texte"]), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        if section.get("image_bytes"):
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    tmp.write(section["image_bytes"])
                    tmp_path = tmp.name
                img_w = pdf.w - 2 * pdf.l_margin
                est_h = _estimate_image_height(section["image_bytes"], img_w)
                # `set_auto_page_break` ne se déclenche que sur cell()/multi_cell(), pas
                # sur un image() positionné explicitement : sans cette vérification
                # manuelle, une image qui ne tient pas dans l'espace restant se
                # retrouvait tronquée en bas de page, et le reste perdu (bug constaté
                # visuellement : un graphique coupé au bas d'une page et absent de la
                # suivante).
                if pdf.get_y() + est_h > pdf.h - pdf.b_margin:
                    pdf.add_page()
                # x/y explicites : sans eux, fpdf2 réutilise la position courante du
                # curseur, qui n'est pas toujours revenue à la marge gauche après un
                # multi_cell() précédent — l'image se retrouvait alors collée au bord
                # droit de la page, tronquée (bug constaté visuellement au rendu).
                # Passer y explicitement signifie aussi que fpdf2 n'avance plus lui-même
                # le curseur après l'image (il ne le fait que pour un placement "au fil du
                # texte") : sans avancer nous-mêmes `pdf.y` avec la hauteur réellement
                # rendue, le contenu suivant se superposait à l'image (bug constaté lui
                # aussi visuellement, pages 1-2 du premier rendu de test).
                info = pdf.image(tmp_path, x=pdf.l_margin, y=pdf.get_y(), w=img_w)
                pdf.set_xy(pdf.l_margin, pdf.get_y() + info.rendered_height + 4)
            finally:
                if tmp_path:
                    os.unlink(tmp_path)
        if section.get("tableau") is not None and not section["tableau"].empty:
            df_t = section["tableau"]
            larg = pdf.w - 2 * pdf.l_margin
            # largeurs proportionnelles au contenu (bornées), pour éviter le chevauchement des colonnes
            poids = []
            for col in df_t.columns:
                n = max([len(str(col))] + [len(str(v)) for v in df_t[col].head(200)])
                poids.append(min(max(n, 6), 45))
            widths = [larg * w / sum(poids) for w in poids]
            # Même logique que pour les images : garantir au moins l'en-tête + 2
            # lignes de données sur la page courante, sinon l'en-tête se
            # retrouvait seul, coupé en bas de page, et les données continuaient
            # sans en-tête sur la page suivante (bug constaté visuellement).
            if pdf.get_y() + 6 + 2 * 5.5 > pdf.h - pdf.b_margin:
                pdf.add_page()
            pdf.set_x(pdf.l_margin)  # défensif : ne jamais hériter d'un curseur hors marge gauche
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_fill_color(230, 236, 245)
            pdf.set_text_color(31, 56, 100)
            for col, w in zip(df_t.columns, widths):
                pdf.cell(w, 6, _fit(pdf, str(col), w), border=1, fill=True)
            pdf.ln()
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(40, 40, 40)
            for _, row in df_t.iterrows():
                for val, w in zip(row, widths):
                    pdf.cell(w, 5.5, _fit(pdf, str(val), w), border=1)
                pdf.ln()
        pdf.ln(5)

    return bytes(pdf.output())


# ---------------------------------------------------------------------------
# Assemblage du rapport de synthèse globale de cette application (Home +
# RH + régions + fonds revolving + suivi de projets + recommandations).
# ---------------------------------------------------------------------------
def build_global_report(data, projets_view: pd.DataFrame, revolving_view: pd.DataFrame | None,
                         recommandations: list[dict], genere_le: str) -> bytes:
    from utils.data import NAVY, BLUE, GOLD, RED, GREEN, AMBER
    from utils.ui import plotly_base_layout

    kpis = []
    ks = data.kpis_solar or {}
    kr = data.kpis_rh or {}
    kpis.append(("Sites installés", str(int(ks.get("SITES INSTALLÉS", 0) or 0))))
    kpis.append(("Puissance totale (kWc)", f"{ks.get('PUISSANCE TOTALE (kWc)', 0):,.0f}".replace(",", " ")))
    kpis.append(("Équipes constituées", str(kr.get("ÉQUIPES CONSTITUÉES", "-"))))
    kpis.append(("Total manques RH", str(kr.get("TOTAL MANQUES", "-"))))
    kpis.append(("Projets suivis", str(len(projets_view) if projets_view is not None else 0)))

    sections = []

    # --- Synthèse RH : grille de statut des équipes ---
    grid = data.grid
    if grid is not None and not grid.empty and "Statut équipe" in grid.columns:
        counts = grid["Statut équipe"].value_counts()
        fig = go.Figure(data=[go.Pie(labels=counts.index, values=counts.values, hole=0.5,
                                      marker=dict(colors=[GREEN, AMBER, RED]))])
        fig = plotly_base_layout(fig, height=320, legend=True)
        sections.append({
            "titre": "Statut des 16 équipes terrain",
            "texte": "Répartition Complète / Partielle / Critique, à partir de la feuille Dashboard du "
                     "classeur AER.",
            "image_bytes": _fig_to_png_bytes(fig),
            "tableau": None,
        })

    # --- Plan d'action RH prioritaire (top 10) ---
    ap = data.action_plan
    if ap is not None and not ap.empty:
        sections.append({
            "titre": "Plan d'action RH prioritaire (top 10)",
            "texte": "Équipes avec le plus de postes manquants, et recommandation associée (recrutement "
                     "externe ou redéploiement), telles que calculées dans le classeur AER.",
            "image_bytes": None,
            "tableau": ap.sort_values("Postes manquants", ascending=False).head(10).astype(str),
        })

    # --- Répartition régionale ---
    syn = data.synthese_region
    if syn is not None and not syn.empty:
        region_level = syn[syn["Niveau"] == "Sous-total région"]
        fig = go.Figure()
        fig.add_bar(x=region_level["Région"], y=region_level["Nb sites"], marker_color=NAVY)
        fig = plotly_base_layout(fig, height=320, legend=False)
        sections.append({
            "titre": "Nombre de sites par région",
            "texte": "Les régions Nord-Ouest, Sud-Ouest et Extreme-Nord (NOSO + Extreme-Nord) sont les "
                     "zones prioritaires de relance identifiees dans l'analyse strategique.",
            "image_bytes": _fig_to_png_bytes(fig),
            "tableau": None,
        })

    # --- Suivi de projets ---
    if projets_view is not None and not projets_view.empty:
        counts = projets_view["Statut"].value_counts()
        fig = go.Figure(data=[go.Pie(labels=counts.index, values=counts.values, hole=0.5,
                                      marker=dict(colors=[GOLD, BLUE, RED, AMBER, GREEN][:len(counts)]))])
        fig = plotly_base_layout(fig, height=320, legend=True)
        a_relancer = projets_view[projets_view["Statut"].isin(["Planifié", "Suspendu"])]
        sections.append({
            "titre": "Suivi de projets — statut",
            "texte": f"{len(projets_view)} projet(s) suivi(s), dont {len(a_relancer)} a relancer "
                     f"(suspendu/planifie), {int((projets_view['Région prioritaire (NOSO / Extrême-Nord)'] == 'Oui').sum())} "
                     "en region prioritaire (NOSO / Extreme-Nord).",
            "image_bytes": _fig_to_png_bytes(fig),
            "tableau": a_relancer[["Site", "Région", "Statut", "Jours depuis dernier mouvement"]].head(15).astype(str)
            if not a_relancer.empty else None,
        })
    else:
        sections.append({
            "titre": "Suivi de projets",
            "texte": "Aucun projet saisi dans le registre de suivi pour l'instant (page Suivi de projets).",
            "image_bytes": None, "tableau": None,
        })

    # --- Fonds revolving ---
    if revolving_view is not None and not revolving_view.empty and "Montant à rembourser (FCFA)" in revolving_view.columns:
        total_a_rembourser = revolving_view["Montant à rembourser (FCFA)"].sum()
        total_rembourse = revolving_view["Montant remboursé à ce jour (FCFA)"].sum()
        taux = (total_rembourse / total_a_rembourser * 100) if total_a_rembourser else 0
        sections.append({
            "titre": "Fonds revolving (Composante 3 du PERACE)",
            "texte": f"{len(revolving_view)} dossier(s) suivi(s), taux de recouvrement global {taux:.1f} %.",
            "image_bytes": None, "tableau": None,
        })

    # --- Recommandations de l'agent conseil ---
    if recommandations:
        lignes = []
        for r in recommandations[:15]:
            lignes.append({"Priorité": r["priorite"], "Catégorie": r["categorie"], "Recommandation": r["titre"]})
        sections.append({
            "titre": "Recommandations de l'agent conseil (top 15)",
            "texte": "Produites par un moteur de règles déterministe — chaque ligne est reliée à un chiffre "
                     "réel de l'application (voir la page Agent conseil pour le détail).",
            "image_bytes": None,
            "tableau": pd.DataFrame(lignes),
        })

    return build_pdf_report(
        "Rapport de synthèse — AER Parc solaire & Ressources humaines",
        "Réactivité des agents, suivi des projets, relance NOSO / Extrême-Nord",
        genere_le, kpis, sections,
    )
