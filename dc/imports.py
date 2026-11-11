"""Import des données sensibles de la cartographie réseau (document Word fourni par la SDMSE) vers la base.
Rien de ce contenu n'est écrit dans le code ni dans le dépôt."""
from __future__ import annotations

import io
import re

import pandas as pd


def _txt(cell) -> str:
    return re.sub(r"\s+", " ", " ".join(p.text for p in cell.paragraphs)).strip()


def lire_cartographie(contenu: bytes) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Retourne (plan d'adressage, constats) lus dans les tableaux du document."""
    from docx import Document
    doc = Document(io.BytesIO(contenu))
    ip, cst = [], []
    for tb in doc.tables:
        entete = [_txt(c).lower() for c in tb.rows[0].cells]
        lignes = [[_txt(c) for c in r.cells] for r in tb.rows[1:]]
        if entete and entete[0].startswith("plage"):
            for c in lignes:
                if c[0]:
                    ip.append({"plage": c[0], "vlan": c[1], "usage": c[2], "passerelle": c[3], "equipements": c[4]})
        elif len(entete) >= 4 and entete[0].startswith("n") and "constat" in entete[1]:
            for c in lignes:
                if c[1]:
                    cst.append({"numero": c[0], "constat": c[1], "equipements": c[2], "nature": c[3]})
    return pd.DataFrame(ip), pd.DataFrame(cst)
