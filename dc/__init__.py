"""Module de maintenance du Data Center (Huawei FusionModule800) de l'AER.

Organisation :
- modele.py      : tables relationnelles « dc_* » (SQLAlchemy Core)
- regles.py      : seuils, détection des écarts, échéances, escalade, indicateurs (fonctions pures, testées)
- depot.py       : lecture / écriture en base et journal d'audit
- referentiel.py : contenu initial non sensible (équipements, listes de contrôle, seuils)
- imports.py     : import des données sensibles (cartographie réseau) depuis le document Word
- exploitation.py  : alertes et acquittement, escalade, main courante, passation de consignes, annuaire (lot 2)
- notifications.py : envoi par courriel (SMTP) et Telegram ; configuration lue dans les secrets, jamais dans le code
"""
