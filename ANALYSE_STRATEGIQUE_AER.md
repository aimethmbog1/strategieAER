# Analyse stratégique — Réactivité des agents, suivi des projets, relance NOSO / Extrême‑Nord
### Plateforme « Gestion_Parc_Solaire » (aer‑dashboard2027.streamlit.app/Parc_solaire)

*Préparé pour aime thierry — 14 octobre 2026*

---

## 0. Méthode et périmètre réel de cette analyse (à lire avant tout)

Je n'ai **pas pu ouvrir la plateforme en direct**. `aer-dashboard2027.streamlit.app` a présenté exactement le même symptôme que `aermeterdashboard.streamlit.app` lors d'une session précédente : seul le squelette générique de Streamlit Cloud s'est affiché (lien "Streamlit Cloud", avatar du créateur, aucun contenu applicatif), même après plusieurs rechargements et ~30 secondes d'attente, sans bouton de réveil détectable. L'app est très probablement en veille (hébergement gratuit Streamlit Community Cloud qui met les apps en pause après inactivité) ou ne démarre pas.

J'ai donc basé cette analyse sur le **code source réel** du projet trouvé dans ton dossier connecté `Documents/keyce/streamlit_app/` (`Home.py` + 8 pages + `utils/`), dont la structure (pages nommées `1_🗺️_Carte_électrification.py` … `8_🔌_Statistiques_compteurs.py`, page « Parc_solaire ») correspond à l'URL demandée et au compte créateur (`aimethmbog1`). C'est une inférence à haute confiance mais **pas une vérification visuelle directe** : si le déploiement réel diffère de ce code (version plus ancienne, branche différente), certains constats ci-dessous devront être ajustés une fois l'app réveillée.

**Ce que ce document fait :** répond à la demande en trois temps — (1) diagnostic honnête de ce que l'outil actuel permet et ne permet pas de faire pour les quatre objectifs stratégiques cités, (2) suggestions stratégiques, (3) proposition d'implémentation pour l'onglet de rapports et l'agent IA, avec les décisions qui t'appartiennent avant que je code quoi que ce soit.

---

## 1. Objectif de la demande (reformulé)

Trois demandes distinctes, imbriquées :

1. **Une analyse stratégique** (casquette RH + gestion matérielle d'un établissement public à caractère technique) pour que la plateforme serve une stratégie visant à : (a) accélérer la réactivité des agents de terrain, (b) assurer un suivi efficace des projets en cours, (c) reprendre des projets d'électrification à l'arrêt, (d) relancer les projets dans les régions en crise (NOSO, Extrême‑Nord).
2. **Un nouvel onglet** de génération automatique de rapports.
3. **Un agent IA intégré** donnant des conseils d'orientation.

## 2. Hypothèses implicites que j'ai dû poser

- « Cette plateforme » = le dépôt `streamlit_app` (app « Gestion_Parc_Solaire »), pas `AER_METERDASHBOARD` (travaillé plus tôt dans la session) ni le classeur Excel source lui-même. Les deux applications Streamlit existent en parallèle sur ton compte et partagent une **copie dupliquée** (pas liée) du module `compteurs.py` — celle de `streamlit_app` n'a pas les améliorations phase-par-préfixe faites sur `AER_METERDASHBOARD`.
- « Agents » désigne le personnel terrain (ingénieurs, techniciens, chauffeurs, agents communautaires) suivi dans la feuille "Données - Équipes", pas les agents commerciaux du Fonds revolving — même si la même logique s'appliquerait aux deux.
- « Projets d'électrification » = les sites/antennes du parc solaire (et plus largement les extensions réseau ENEO financées par le Fonds revolving), pas un portefeuille de projets au sens chef-de-projet (jalons, budget, contrat) — **cette notion n'existe pour l'instant dans aucune donnée de l'application** (voir §4).
- Tu valides du code et un déploiement progressif (comme pour les rounds précédents sur AER_METERDASHBOARD), pas uniquement un document d'analyse.

Si l'une de ces hypothèses est fausse, le reste de l'analyse peut être à corriger.

## 3. Informations manquantes critiques — à signaler explicitement, pas à deviner

C'est le point le plus important de toute cette analyse : **l'application actuelle est un outil de photographie de capacité (combien de sites, combien d'agents, combien de kWc), pas un outil de suivi de processus.** Pour répondre sérieusement aux quatre objectifs stratégiques cités, il manque des données qui n'existent nulle part dans le classeur Excel ni dans l'app :

| Donnée nécessaire | Existe aujourd'hui ? |
|---|---|
| Statut d'avancement par projet/site (planifié / en cours / suspendu / repris / terminé) | **Non** — seul un statut d'équipe (Complète/Partielle/Critique) et un "Phase" (I/II/III, probablement calendaire) existent |
| Historique des incidents / demandes / tickets et leur délai de traitement (= "réactivité") | **Non** — aucune donnée d'activité ou d'horodatage d'intervention |
| Raison et date de suspension d'un projet à l'arrêt | **Non** |
| Budget engagé / décaissé par projet (hors Fonds revolving, qui est un mécanisme distinct) | **Non** |
| Référentiel de contact agent (téléphone, disponibilité) pour mesurer/accélérer la réactivité | **Non** |

Le classeur contient en revanche de quoi **cibler** une stratégie de relance régionale : les 499 sites sont déjà rattachés à une Région/Département, et les noms de régions couvrant le NOSO et l'Extrême‑Nord apparaissent déjà dans l'app (ex. délégations "DRONO" = Bamenda/Nord‑Ouest, "DRSOM" = Kumba/Limbe/Sud‑Ouest, "DRNEA" = Nord/Extrême‑Nord, dans le module Fonds revolving ; la feuille "Données sites" a elle aussi une colonne Région). Donc on peut déjà **mesurer un retard relatif** (sites non desservis, personnel manquant par région) mais pas **une dynamique de projet** (ce qui bloque, depuis quand, qui doit agir).

**Conséquence directe :** un "agent IA de conseil" ou un "rapport automatique" bâtis uniquement sur les données déjà présentes donneront des recommandations de capacité ("il manque 3 techniciens à l'antenne X"), pas des recommandations de pilotage de projet ("le projet Y est bloqué depuis 4 mois pour raison Z, voici l'action"). Si l'objectif réel est le second, il faut d'abord créer une brique de saisie de suivi de projet (sur le même principe que le registre du Fonds revolving : vide au départ, alimentée par toi/les agents, exportable en CSV). Je te propose ce choix explicitement en question 1 ci-dessous plutôt que de le décider à ta place.

## 4. Diagnostic honnête de l'outil actuel face aux 4 objectifs

- **Accélérer la réactivité des agents** : l'app montre *qui manque où* (grille des 16 équipes, manques par profil/antenne, personnel non affecté). C'est un **levier indirect** de réactivité (combler les postes vacants réduit la charge par agent, donc améliore les délais), mais il n'y a aucune mesure directe de délai de réponse. Point fort exploitable : la carte calcule déjà une distance réelle (Haversine) site↔antenne et une charge "sites par agent" — un bon point de départ pour prioriser qui est objectivement en surcharge/éloignement.
- **Suivi efficace des projets en cours** : actuellement, "suivi" = une photo statique (sites installés, puissance, personnel). Pas de notion de "en cours" vs "terminé" vs "en retard". Les KPI du Fonds revolving et des compteurs sont eux bien **vivants** (registre alimenté en continu, indicateurs calculés en direct) — c'est le modèle à répliquer pour un vrai suivi de projet.
- **Reprise de projets à l'arrêt** : aucune donnée ne distingue aujourd'hui un site "jamais commencé" d'un site "commencé puis arrêté". Il faudrait au minimum un statut et une date de dernier mouvement par site/antenne.
- **Relance NOSO / Extrême‑Nord** : les régions existent dans le référentiel géographique, donc un filtre/priorisation régionale est **immédiatement faisable** avec les données déjà là (ex. : nombre de sites non encore installés par région, écart effectif requis/pourvu par région, carte déjà filtrable par région). Ce qui manque est la dimension "projet actif ou arrêté" pour distinguer une région en retard structurel d'une région dont les projets ont été interrompus (souvent pour raisons sécuritaires dans ces deux zones, mais l'app ne capture aujourd'hui aucune raison de blocage).

## 5. Trois approches stratégiques alternatives (et pourquoi j'écarte ou retiens chacune)

**A. Rester purement dans les données existantes** — n'ajouter *que* l'onglet rapport et l'agent IA, construits sur les KPI déjà calculés (capacité, écarts RH, puissance, recouvrement du fonds).
*Avantages* : rapide, zéro nouvelle saisie, zéro risque de données incohérentes.
*Inconvénients* : ne répond que partiellement à 2 des 4 objectifs (suivi de projet, reprise de projets à l'arrêt) puisque la donnée "statut de projet" n'existe pas. Le rapport automatique et l'IA seraient alors des "rapports de capacité", pas des "rapports de pilotage".

**B. Ajouter une brique "Suivi de projets" (recommandée)** — un registre éditable par site/antenne (statut, date de dernier mouvement, blocage déclaré, région prioritaire), sur le modèle déjà validé du Fonds revolving : démarre vide, alimenté en continu, exportable en CSV, jamais de données inventées.
*Avantages* : seule option qui couvre réellement les 4 objectifs ; réutilise un pattern déjà éprouvé dans ton appli (donc cohérent, peu de risque technique) ; donne à l'onglet rapport et à l'agent IA une vraie matière pour parler de *processus* et pas seulement de *capacité*.
*Inconvénients* : demande un effort de saisie humain régulier (sans lui, le registre reste vide et le bénéfice est nul) ; pas de persistance entre sessions Streamlit (comme le Fonds revolving) sauf si on branche une base de données externe (voir C).
*Risque principal* : si personne ne maintient le registre à jour, l'outil donne une fausse impression de suivi ("rien n'est marqué en retard" peut vouloir dire "tout va bien" ou "personne n'a mis à jour" — ambiguïté à afficher explicitement dans l'UI, comme on l'a fait pour les désaccords de phase sur AER_METERDASHBOARD).

**C. Ajouter une vraie base de données persistante (ex. Google Sheets, Airtable, PostgreSQL via Streamlit secrets) pour le suivi de projet** plutôt qu'un registre en mémoire de session.
*Avantages* : résout le problème de perte de données entre sessions, permet une saisie à plusieurs mains (agents terrain), historique daté fiable — répond le mieux, à terme, à "suivi efficace" et "reprise de projets".
*Inconvénients* : complexité et coût opérationnel largement supérieurs (compte de service, clés d'API en secret Streamlit Cloud, gestion des accès concurrents, maintenance) ; sort du périmètre "petit tableau de bord Streamlit" ; risque de sur-ingénierie si l'usage réel reste un ou deux agents.

**Recommandation** : B maintenant (cohérent avec l'existant, livrable rapidement), C comme évolution si l'usage réel démontre le besoin de plusieurs contributeurs simultanés et d'un historique inter-sessions fiable. Je n'implémente pas C sans que tu le demandes explicitement — c'est un changement d'infrastructure, pas une fonctionnalité Streamlit classique.

## 6. Auto-critique de cette recommandation

Deux failles possibles dans mon propre raisonnement :
- Je suppose que l'absence de données de suivi de projet est un vrai manque métier et non un choix délibéré (peut-être que l'AER suit déjà ses projets ailleurs — un autre système, un tableau Excel séparé — et que la demande ne visait que l'ajout des deux fonctionnalités techniques sur les données déjà là). Si c'est le cas, l'option A suffit et mon option B serait un travail non désiré.
- Je m'appuie sur le code lu localement, qui peut ne pas être exactement ce qui tourne en production (voir §0). Si la version déployée a déjà une brique de suivi de projet que je n'ai pas vue, une partie du diagnostic du §4 serait caduque.

C'est pourquoi la question 1 ci-dessous (avant tout code) porte justement sur ce point.

## 7. L'onglet « Génération automatique de rapports »

### Approches possibles

1. **Rapport PDF unique "snapshot"** (même pattern que le PDF déjà construit sur AER_METERDASHBOARD avec `fpdf2` + `kaleido`) : KPI de la page d'accueil + synthèse RH + synthèse régionale + (si tu retiens l'option B) statut des projets, filtrable par région/antenne/période. Simple, cohérent avec l'existant, pas de dépendance externe payante.
2. **Export Excel multi-feuilles** (une feuille par thématique) plutôt que PDF — plus utile si le rapport doit être retravaillé (tableaux croisés) par d'autres services, moins adapté à une présentation institutionnelle.
3. **Rapport "narratif" généré par un LLM** à partir des mêmes données (texte de synthèse en langage naturel plutôt que tableaux) — dépend entièrement du choix fait pour l'agent IA (§8), et introduit un risque d'hallucination sur des chiffres si mal cadré (toujours recalculer les chiffres par le code, ne jamais laisser le LLM les inventer).

**Recommandation** : commencer par 1 (PDF), qui réutilise un code déjà testé et validé sur ton autre app, puis éventuellement ajouter 2 en complément (les deux ne s'excluent pas). Je ne retiens pas 3 comme méthode de calcul des chiffres — seulement, si tu choisis un agent IA conversationnel (§8), comme habillage textuel optionnel au-dessus de chiffres déjà calculés par le code.

### Question ouverte
Quel périmètre exact pour ce rapport : une synthèse globale unique, ou un rapport paramétrable par région/antenne (utile en particulier pour appuyer la relance NOSO/Extrême‑Nord auprès d'une direction ou d'un bailleur) ? Les deux sont faisables, mais le second demande plus de travail de mise en page (sections conditionnelles).

## 8. L'« agent IA » de conseil — trois architectures, pas une seule

C'est le choix le plus structurant techniquement, donc celui que je ne veux pas trancher à ta place.

**Option 1 — Moteur de règles déterministe (recommandé par défaut).**
Un module qui scanne les KPI déjà calculés (écarts RH par antenne, taux de recouvrement du fonds, retards par région, et — si tu valides l'option B — statuts de projet) et produit des recommandations textuelles prédéfinies et explicables ("Antenne de Bamenda : 3 postes manquants sur 4 → risque élevé, recruter en priorité" ; "Région Extrême‑Nord : aucun mouvement de projet enregistré depuis la phase 2 → proposer une relance"). 
*Avantages* : gratuit, instantané, aucune clé API ni secret à gérer sur un déploiement public, résultat 100 % traçable (chaque conseil est relié à un chiffre vérifiable, pas de boîte noire) — cohérent avec toute la philosophie "jamais de donnée inventée" déjà appliquée partout ailleurs dans tes deux applications.
*Inconvénients* : moins "intelligent" en apparence, ne répond pas à une question libre en langage naturel, les règles doivent être écrites et maintenues à la main.

**Option 2 — Agent conversationnel branché sur une API LLM (OpenAI/Anthropic/autre).**
Un vrai chat où l'utilisateur pose une question libre, le code lui fournit en contexte les données déjà calculées (jamais brutes/non vérifiées), et le LLM formule la réponse.
*Avantages* : plus flexible, répond à des questions non anticipées, formulation plus naturelle.
*Inconvénients et risques* : nécessite une clé API payante stockée en secret Streamlit Cloud (coût récurrent, à ta charge, et à sécuriser — une app publique ne doit jamais exposer cette clé côté client) ; risque d'hallucination si le prompt n'est pas strictement cadré (le LLM doit citer uniquement les chiffres qu'on lui fournit, jamais en inventer) ; dépendance à un service tiers (si la clé expire ou le quota est atteint, la fonctionnalité tombe en panne) ; pour un outil institutionnel public, la responsabilité d'une recommandation erronée générée par un tiers est plus délicate à assumer que celle d'une règle écrite et relue par toi.

**Option 3 — Hybride.**
Le moteur de règles (Option 1) comme socle fiable et gratuit, avec en option — seulement si une clé API est fournie dans les secrets Streamlit — un habillage conversationnel par-dessus (reformulation en langage naturel des mêmes recommandations, et réponse à des questions de suivi). Si la clé n'est pas configurée, l'app bascule automatiquement sur l'affichage brut des règles, sans jamais planter.

**Recommandation** : Option 1 en premier livrable (fonctionne immédiatement, zéro coût, zéro risque de sécurité), avec l'Option 3 comme extension native si tu obtiens une clé API et veux aller plus loin — le code sera écrit de façon à permettre cette extension sans tout refaire.

## 9. Ce qui reste incertain — à ne pas me faire deviner

- Je ne sais pas si l'AER dispose déjà d'un système de suivi de projet ailleurs (Excel séparé, autre logiciel) que cette plateforme devrait venir compléter ou remplacer.
- Je ne sais pas si un budget existe pour une clé API LLM récurrente (Option 2/3 de l'agent IA) ni qui la gérerait en continu.
- Je n'ai pas pu confirmer visuellement l'état réel du déploiement en production (voir §0) — mes constats s'appuient sur le code source local, à haute confiance mais non vérifiés en direct.
- Les causes réelles de blocage des projets en NOSO/Extrême‑Nord (sécurité, logistique, financement, autre) ne sont documentées nulle part dans les données disponibles ; toute recommandation de "relance" formulée ici reste générique (prioriser, sécuriser l'accès, phaser différemment) tant que cette information n'est pas saisie quelque part.

## 10. Suggestions stratégiques concrètes (dans le cadre des données réellement disponibles aujourd'hui)

1. **Réactivité des agents** : publier sur la page d'accueil un indicateur de charge réelle (sites/agent, déjà calculé) trié par antenne, avec seuil d'alerte visuel — permet de rediriger en priorité les recrutements/affectations vers les zones objectivement en surcharge, ce qui réduit mécaniquement les délais d'intervention.
2. **Suivi des projets en cours** : avant tout outil automatisé, créer la brique de suivi de projet (option B, §5) — sans elle, "suivi efficace" restera une formule sans données pour la supporter.
3. **Reprise des projets à l'arrêt** : une fois la brique créée, un simple filtre "Statut = Suspendu" trié par date de dernier mouvement donne immédiatement la liste priorisée à traiter — pas besoin d'IA pour ça, juste de la donnée saisie.
4. **Relance NOSO / Extrême‑Nord** : dès maintenant, sans aucun développement, un filtre région sur la carte et sur la page Répartition régionale permet de chiffrer précisément le retard relatif de ces deux zones (sites non desservis, écarts RH) — un argumentaire chiffré utile pour appuyer une décision de relance, même avant d'avoir la brique de suivi de projet.

## 11. Ce qu'il me faut de toi avant de coder

Voir les questions posées juste après ce document (portée du suivi de projet, architecture de l'agent IA, périmètre du rapport). Tant que ces trois points ne sont pas tranchés, je risque de construire quelque chose qui ne correspond pas à l'usage réel visé, ou de devoir tout refaire.
