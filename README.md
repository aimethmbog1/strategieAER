# Tableau de bord AER — Application Streamlit

Application de visualisation pour le classeur `Gestion_Parc_Solaire_AER2027_DASHBOARD.xlsx`
(parc solaire + ressources humaines terrain). Toutes les feuilles du classeur sont
exploitées : Dashboard, Antennes — Détail solaire, Données sites, Répartition par
antenne, Synthèse par région, Organigramme, Données - Équipes, Notes & méthodologie.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install -r requirements.txt
```

## Lancement

```bash
streamlit run Home.py
```

L'application s'ouvre sur `http://localhost:8501`. Un fichier `data.xlsx` (le
tableau de bord AER) est fourni par défaut ; vous pouvez à tout moment charger un
autre classeur via le sélecteur de fichier dans la barre latérale, sur n'importe
quelle page.

## Sécurité, stockage et déploiement

L'accès est protégé par comptes et rôles ; les registres sont enregistrés durablement ; la procédure de mise en service (Streamlit Cloud puis Data Center de l'AER) est décrite dans **DEPLOIEMENT.md**.

## Structure du projet

```
Home.py                              Page d'accueil : tableau de bord à onglets reprenant les statistiques
                                      de chaque page (jauges, graphiques en anneau, barres — jamais de
                                      simples nombres), onglet « Vue d'ensemble » (KPI, grille des 16
                                      équipes, plan d'action prioritaire) inchangé
pages/
  1_🗺️_Carte_électrification.py     Carte unique : sites, antennes, distances, charge de personnel,
                                      statistiques par phase
  2_🛰️_Parc_solaire.py              Dimensionnement par antenne + tableau des 499 sites
  3_👷_Équipes_terrain.py           Détail des équipes + personnel non affecté
  4_🌍_Répartition_régionale.py     Répartition par antenne / région / département
  5_🏢_Organigramme.py              Hiérarchie du réseau d'antennes (sunburst) + mouvement de personnel
  6_📝_Notes.py                     Notes & méthodologie (recherche plein texte)
  7_💰_Fonds_revolving.py           Suivi du fonds revolving (Composante 3 du PERACE)
  8_🔌_Statistiques_compteurs.py    Statistiques des compteurs installés, par localité et par période
  9_📌_Suivi_de_projets.py          Suivi d'avancement des projets d'électrification (registre à alimenter)
  10_📄_Rapports.py                  Génération automatique du rapport de synthèse (PDF)
  11_🤖_Agent_conseil.py             Recommandations priorisées (moteur de règles déterministe)
  12_🚗_Parc_automobile.py           Registre des véhicules, affectation, carburant/vidanges, réforme
  13_💼_Masse_salariale.py           Registre de paie, masse salariale (filtres, tris, ventilations), bulletin
  14_🛡️_Administration.py           Stockage, sauvegarde / restauration, comptes, journal des actions (admin)
  15_⚖️_Mentions_et_confidentialité.py  Mentions légales, conditions d'utilisation, données personnelles (loi 2024/017)
  16_📒_Suivi_budgétaire.py          Prévu / engagé / payé et indicateurs par activité (budget SDMSE 2027 pré-chargé)
  17_📡_Supervision_centrales.py     Import des exports de supervision, centrales silencieuses, disponibilité
  18_💵_Recettes_et_abonnés.py       Import des états de vente, recettes, compteurs actifs, taux de réalisation
  19_🚨_Alertes.py                   Alertes automatiques sur tous les registres (+ envoi par courriel)
  20_🎯_Dossier_de_plaidoyer.py      Dossier institutionnel FR / EN sourcé, contrôles de cohérence, PDF + annexe
utils/
  data.py                            Lecture et parsing du classeur (mise en cache)
  geo.py                             Distances (Haversine) et centroïdes d'antenne
  revolving.py                       Personnel de suivi & registre du fonds revolving
  compteurs.py                       Import des exports Holley & statistiques de compteurs
  projets.py                         Registre de suivi de projets (statut, blocage, région prioritaire)
  conseiller.py                      Moteur de règles de l'agent conseil
  rapports.py                        Génération du PDF de synthèse (fpdf2 + kaleido)
  vehicules.py                       Registre du parc automobile, journal d'utilisation, réforme
  personnel.py                       Mouvements de personnel (session) par-dessus le registre RH figé
  paie.py                            Registre de paie, calcul en lot, ventilations, simulation de recrutement
  auth.py                            Comptes, rôles, connexion, journalisation
  storage.py                         Stockage durable des registres (PostgreSQL ou SQLite), sauvegarde complète
  alertes.py                         Règles d'alerte et envoi du récapitulatif
  plaidoyer.py                       Indicateurs sourcés, cohérence, génération du dossier FR / EN
  paie_moteur.py                     Moteur de paie conforme au Statut du personnel (copie de paie_aer.py)
  ui.py                              Composants d'interface & thème partagés
  loader.py                          Chargement du fichier, partagé entre les pages
data.xlsx                            Classeur AER fourni par défaut
data/parametres_paie_aer.json        Grille, primes, taux et options de paie (Statut du personnel + retenues légales)
```

## Habillage visuel — inspiré de tertullien.com

L'application reprend le système visuel du site **tertullien.com** (plateforme d'identité médicale
d'urgence) : fond neutre, vert forêt profond comme couleur de marque, cartes blanches à coins
arrondis et ombre légère teintée de vert, titres en **Outfit** (gras, géométrique) et texte/contrôles
en **Plus Jakarta Sans**. Concrètement :

- **`.streamlit/config.toml`** porte l'essentiel du thème (couleurs natives, polices via Google
  Fonts, rayons de bordure, en-têtes de `st.dataframe`) — c'est la méthode native recommandée par
  Streamlit, plus robuste qu'une CSS injectée face aux mises à jour de version.
- **`utils/ui.py` (`inject_base_style`)** complète uniquement ce que `config.toml` ne couvre pas :
  la carte des KPI (`st.metric` habillé en « feature card » blanche avec ombre), le bandeau de
  titre de section (`section_title`, teinte menthe + texte vert foncé) et les badges de statut.
- **Les couleurs des graphiques Plotly restent inchangées** (`NAVY`/`BLUE`/`GOLD`/`STATUS_COLORS`
  dans `utils/data.py`) : c'est un choix délibéré, pas un oubli — ce système de couleurs a été
  validé (lisibilité, daltonisme) et reste cohérent sur les 13 pages ; seul l'« habillage » de
  l'application (fond, typographie, cartes, boutons, barre latérale) a été retravaillé.

## La carte d'électrification — ce qu'elle fait et ce qu'elle ne fait pas

C'est la page la plus riche de l'application, pensée pour rester honnête sur ce que
les données permettent réellement :

- **Sites** géolocalisés à leurs coordonnées GPS réelles, colorables par antenne,
  région ou phase, taille proportionnelle à la puissance, filtres combinables
  (antenne, région, phase, puissance, recherche par nom).
- **Antennes** affichées en losanges à leur **centroïde calculé** (barycentre des
  sites rattachés) — l'AER n'a pas fourni les coordonnées réelles du siège de
  chaque antenne dans ce classeur, donc l'application ne les invente pas et le
  dit explicitement dans l'encadré méthodologique de la page.
- **Hiérarchie du réseau** tracée entre antennes à partir de la colonne réelle
  « Rattachée à » de la feuille Antennes — Détail solaire.
- **Charge de personnel** : les antennes peuvent être colorées par leur ratio
  réel « sites / agent » pour repérer les zones les plus chargées.
- **Distances** : chaque site a sa distance orthodromique (Haversine, à vol
  d'oiseau — pas une distance routière) au centroïde de son antenne, plus un
  outil pour mesurer la distance entre deux sites choisis.
- **Ce qui n'est volontairement pas superposé** : le statut réel des 16 équipes
  terrain (feuille Données - Équipes) utilise un découpage par région qui ne
  correspond pas antenne pour antenne au découpage des sites — le mélanger sur
  la carte créerait un lien géographique faux. Cette donnée reste consultable
  sur la page « Équipes terrain », et la table de fréquence de visite du
  référentiel RH est quand même montrée en clair (non géolocalisée) sur la page
  carte, avec le même avertissement.
- **Statistiques par phase** : nombre de sites et puissance (kWc) par phase
  (1/2/3), recalculées en direct sur la sélection filtrée (pas seulement sur les
  499 sites totaux) — donut + barre + tableau, juste sous les KPI de la carte.

## L'organigramme du réseau d'antennes — ce qu'il fait et ce qu'il ne fait pas

Deux schémas hiérarchiques distincts, volontairement **jamais fusionnés** (même
raison que sur la carte d'électrification : les deux feuilles source découpent
les antennes différemment) :

- **« Siège & antennes » (parc solaire)** : antennes du parc solaire (nommées
  par ville), taille = **effectif recommandé** de la feuille Antennes — Détail
  solaire (une cible, pas l'effectif réel). Rendu en *sunburst* Plotly (police
  Outfit, teintes de marque) — forme et typographie retravaillées sur demande
  explicite pour ce schéma précis, contrairement au reste des graphiques de
  l'application dont la palette reste celle de `utils/data.py`.
- **« Répartition actuelle du personnel » (référentiel RH)** : antennes de la
  feuille Données - Équipes (nommées par région — Nord, Adamaoua, Est…, un
  découpage différent des antennes solaires ci-dessus), affichées **à plat**
  (le classeur ne fournit aucune colonne de rattachement hiérarchique entre
  elles, contrairement à la feuille solaire qui a « Rattachée à »). Taille =
  **effectif réellement en poste maintenant** ; couleur = taux de couverture
  des 4 postes-types de l'antenne (vert ≥ 90 %, orange 50-90 %, rouge < 50 %).
- **Mouvement de personnel** : déplace un agent — y compris depuis le pool
  « personnel non affecté à une équipe » — vers un autre poste (une équipe
  précise, vacante ou déjà occupée — auquel cas un échange a lieu — ou vers le
  pool). Gérée par `utils/personnel.py`, en session uniquement, sur le même
  principe que les autres registres éditables (parc auto, fonds revolving,
  suivi de projets) : le classeur source n'est **jamais** modifié, un journal
  horodaté des mouvements est tenu, et tout est réinitialisable en un clic.
  Toutes les pages qui dépendent du personnel lisent ce registre **effectif**
  (classeur + mouvements) plutôt que les données brutes du classeur, pour que
  Home, Équipes terrain, Organigramme et le besoin d'acquisition de véhicules
  (côté chauffeurs) se mettent à jour automatiquement après chaque mouvement.

## Le fonds revolving (Composante 3 du PERACE) — ce qu'il fait et ce qu'il ne fait pas

Le classeur Excel ne contient aucune donnée sur ce fonds : c'est un mécanisme distinct, financé par la
Banque mondiale (crédit IDA, Composante 3 du projet PERACE, P163881), qui aide les ménages à payer les
frais initiaux de raccordement au réseau électrique (extension réseau ENEO), séparément du parc de
mini-centrales solaires documenté ailleurs dans l'application.

- **Personnel de suivi** : la répartition réelle par délégation régionale (DCUD, DCUY, DRC, DRE, DRNEA,
  DRONO, DRSANO, DRSM, DRSOM) et délégation commerciale, avec les 28 agents nommément assignés.
- **Registre des dossiers** : démarre **vide** — ce n'est pas une base de vrais dossiers (non publique),
  mais un outil de saisie que vous alimentez au fil de l'eau (formulaire d'ajout avec sélection en
  cascade région → zone → agent, tableau éditable pour corriger ou supprimer une ligne).
- **Valeurs de référence** pré-remplies dans le formulaire (frais initial 2 000 FCFA, remboursement sur
  6 à 8 ans) : documentées dans les rapports de projet de la Banque mondiale, pas des données déjà
  enregistrées.
- **Indicateurs et graphiques** (montants engagés/remboursés par délégation, taux de recouvrement,
  charge par agent) sont calculés en direct, uniquement à partir des dossiers que vous avez saisis.
- **Persistance** : Streamlit ne conserve rien entre deux sessions. Téléchargez le registre en CSV avant
  de fermer, et rechargez-le à l'ouverture suivante via le bouton dédié.
- **Découpage indépendant de la carte solaire** : les délégations régionales de ce fonds sont une
  organisation commerciale ENEO/AER différente des 9 antennes du réseau solaire — volontairement non
  superposées, pour la même raison de rigueur des données que sur la page Carte.

## Statistiques des compteurs — ce qu'elle fait et ce qu'elle ne fait pas

Comme le Fonds revolving, cette page lit ses **propres fichiers** (déposés indépendamment dans sa barre
latérale) : le classeur Excel du tableau de bord ne contient aucune donnée sur les compteurs/abonnés
installés, qui est un suivi distinct du parc de mini-centrales solaires documenté ailleurs dans
l'application.

- **Format reconnu automatiquement** : l'export du système de gestion des compteurs prépayés « Holley »
  (colonnes `Full Address` / `Template Code`). Sa colonne `Opening Date` est un **champ système figé à
  01/01/2018** sur tous les fichiers observés — elle n'indique donc pas la vraie date d'installation.
  Chaque fichier correspond en réalité à un **lot d'abonnés** exporté à une date donnée, et c'est **la
  date présente dans le nom du fichier** (ex. `01-10-2024.xls`) qui sert de période d'installation pour
  toutes ses lignes — convention confirmée pour ces fichiers, affichée et modifiable avant de lancer les
  statistiques, avec un tableau de traçabilité par lot pour la vérifier. Sa colonne `Holley System ID`
  (ex. « 31K433 ») est un **poste** — l'équipement/poste de configuration Holley ayant servi à
  enregistrer les compteurs — et non un site géographique : le vrai équivalent « site » du reste du
  tableau de bord AER, c'est ici la **localité**, qui est d'ailleurs rapprochée des 499 sites officiels
  du parc solaire (voir ci-dessous).
- **Qualité des localités** : les noms de localités des fichiers réels contiennent de nombreuses
  variantes d'orthographe (coquilles, casse, espaces, noms dupliqués). La correction suggérée se fait en
  deux passes : d'abord un rapprochement avec `data/sites_officiels_aer.csv` (les 499 sites du parc
  solaire, extraits de ce même classeur — feuille « Données sites »), pour reprendre l'orthographe
  officielle quand la ressemblance est forte (ex. `DOUKOUR0Y` → `Doukouroy`) ; puis un regroupement par
  similarité de texte pour les localités restantes. La colonne « Origine de la correction » indique
  laquelle des deux s'applique, et rien n'est fusionné sans validation explicite dans le tableau éditable
  de la barre latérale.
- **Cinq angles d'analyse** : vue d'ensemble (KPI + traçabilité par lot), par localité (avec filtre par
  poste, répartition par type de compteur réseau/solaire), par période (granularité mois/trimestre/année,
  cumul dans le temps), un croisement localité × période (carte de chaleur, Top 12 ou toutes les
  localités) pour repérer où et quand l'effort d'installation s'est concentré, et un suivi par phase du
  projet (compteurs par phase, évolution dans le temps, tableau croisé phase × période). Aucune colonne
  « phase » n'existe dans les exports Holley : les phases sont des plages de dates **éditables dans la
  barre latérale**, pré-remplies en 3 tiers égaux à corriger avec les vraies dates de chaque phase — un
  compteur hors de toute plage définie est compté à part, sous « (hors phase) ».
- **Persistance** : comme pour le Fonds revolving, rien n'est conservé entre deux sessions — tous les
  tableaux (par localité, par période, croisement, par phase, export complet) se téléchargent en CSV.
- **Découpage indépendant du reste de l'application** : les « postes » de ce suivi viennent du système
  Holley et ne sont pas automatiquement recoupés avec les antennes du réseau solaire ni les délégations
  du Fonds revolving, pour la même raison de rigueur des données que sur les autres pages. Les
  « localités », elles, sont bien rapprochées des 499 sites officiels du parc solaire quand la
  ressemblance est forte (voir ci-dessus).

## Suivi de projets, rapports automatiques et agent conseil — ce qu'ils font et ce qu'ils ne font pas

Ces trois pages répondent à une demande de stratégie RH/matériel : accélérer la réactivité des agents,
assurer le suivi des projets en cours, reprendre les projets à l'arrêt, relancer l'électrification dans les
régions en crise (NOSO = Nord-Ouest + Sud-Ouest, et Extrême-Nord). L'analyse complète qui a précédé leur
conception est dans `ANALYSE_STRATEGIQUE_AER.md`, à la racine du projet.

- **Suivi de projets** : comme pour le Fonds revolving, le classeur Excel ne contient **aucune donnée
  d'avancement de projet** (seulement une photo de capacité). Cette page ajoute un **registre à alimenter**,
  rattaché aux 499 sites réels (Région / Antenne / Phase recopiées automatiquement, jamais ressaisies), avec
  un statut (Planifié / En cours / Suspendu / Repris / Terminé), une date de dernier mouvement et un motif de
  blocage. Un marqueur « région prioritaire » (NOSO / Extrême-Nord) et un plan de reprise priorisé par
  ancienneté sont calculés automatiquement. Comme pour le Fonds revolving, **le registre démarre vide** et
  rien n'est conservé entre deux sessions — à exporter/recharger en CSV.
- **Génération automatique de rapports** : assemble en PDF les KPI déjà calculés ailleurs dans l'application
  (statut des équipes, plan d'action RH du classeur, répartition régionale, suivi de projets, Fonds
  revolving, recommandations de l'agent conseil) — réutilise le générateur déjà validé sur l'application
  AER_METERDASHBOARD (`fpdf2` + `kaleido`). Aucune section n'invente de donnée : une source vide (registre
  non alimenté) l'indique explicitement plutôt que d'être simplement absente.
- **Agent conseil** : **pas un agent conversationnel ni un appel à une API LLM** — un moteur de règles
  déterministe, choisi explicitement pour un déploiement public (gratuit, instantané, aucune clé API/secret
  à gérer, aucun risque d'hallucination). Chaque recommandation est reliée à un chiffre réel (plan d'action
  RH du classeur, manques RH par région, charge sites/agent par antenne, projets à relancer, Fonds
  revolving) et les règles elles-mêmes sont documentées dans un encadré de transparence sur la page. Une
  évolution vers un habillage conversationnel (LLM) reste possible sans changer cette logique si une clé API
  est fournie plus tard — voir l'analyse stratégique pour le détail des options considérées.

## Parc automobile — ce qu'elle fait et ce qu'elle ne fait pas

Répond à une demande de gestion logistique du parc DGOER (immatriculation, affectation aux équipes/antennes,
carburant, vidanges, chauffeur, réforme), à partir du fichier `gestionnaire_du_parc_auto_DGOER.xlsx` fourni.

- **Ce qui est réel** : les **12 véhicules** du fichier (Direction/siège — y compris sa sous-rubrique
  « Maîtrise d'œuvre publique » — + 4 antennes), avec plaques, marques et années de mise en service recopiées
  telles quelles, y compris les **4 plaques incomplètes** (préfixe « CE » seul dans le fichier source) et les
  **3 années manquantes**, jamais complétées ou devinées.
- **Incohérence de données signalée, pas masquée** : le fichier parc auto classe les véhicules en **5
  entités** (ex. « Nord / Extrême-Nord / Adamaoua » regroupés) alors que la feuille RH « Données - Équipes »
  utilise **9 antennes** plus fines, qui ne se recouvrent pas exactement. Le champ « Entité propriétaire »
  reste fidèle au fichier parc auto ; le champ « Équipe affectée » est une affectation optionnelle et
  distincte, vers la vraie liste des antennes RH — jamais une correspondance devinée entre les deux.
- **Affectation dynamique (onglet « Affectation »)** : affecter un véhicule à une antenne fait apparaître un
  menu déroulant de chauffeur limité aux agents RÉELS de cette antenne (rôle Chauffeur, statut OK dans la
  feuille RH) — jamais un nom libre. Trois règles sont appliquées au moment de valider : un véhicule n'a
  qu'une seule équipe affectée et qu'un seul chauffeur à la fois, et un même chauffeur ne peut être
  responsable que d'un seul véhicule à la fois (la liste déroulante retire automatiquement les chauffeurs déjà
  pris). Une édition directe du tableau du registre reste possible mais n'est pas bloquée par ces règles ; la
  page détecte alors l'incohérence (chauffeur en double, ou chauffeur qui n'appartient pas à l'antenne
  affectée) et l'affiche explicitement plutôt que de la corriger en silence.
- **Journal d'utilisation horodaté** (plein de carburant, vidange, entretien, panne — avec quantité, coût,
  kilométrage et chauffeur) plutôt qu'une simple fiche cumulative, pour permettre de vraies statistiques
  (consommation cumulée par véhicule, historique des vidanges). Registre et journal démarrent pré-remplis
  (véhicules réels) ou vides (journal) et, comme les autres registres de l'application, ne sont pas
  persistés entre deux sessions — à exporter/recharger en CSV.
- **Date de réforme = estimation, pas une règle officielle** : aucune règle de réforme (ni kilométrage, ni
  durée de vie standard) n'a été communiquée. La page calcule une suggestion à partir d'un **seuil d'âge
  réglable** (7 ans par défaut) appliqué à l'année de mise en service ; la date retenue manuellement par
  l'utilisateur, si elle est renseignée, prime toujours sur cette suggestion.
- **Couverture par antenne = un repère, pas une dotation officielle** : la page signale les antennes RH sans
  aucun véhicule affecté, mais aucun ratio véhicules/agents officiel n'existe dans les classeurs disponibles
  — ce n'est donc pas un calcul de besoin validé.
- **Besoin d'acquisition (onglet « Statistiques & réforme ») = application mécanique de deux règles fixées par
  l'utilisateur**, pas une dotation officielle, combinant deux volets distincts (jamais confondus) :
  1. **« 1 chauffeur = 1 véhicule », calculé antenne par antenne** : pour chaque antenne, besoin = max(0,
     nombre de chauffeurs réels — rôle Chauffeur, statut OK dans la feuille RH — moins nombre de véhicules qui
     lui sont affectés et encore physiquement dans le parc, hors « Réformé / sorti du parc »).
  2. **Réserve fixe « approvisionnement et coordination » de 2 véhicules, ajoutée une seule fois pour toute la
     structure** (pas par antenne — choix explicite de l'utilisateur parmi les répartitions possibles), pour
     couvrir des besoins transverses hors affectation nominative à un chauffeur d'antenne.
  Les véhicules « non affectés » mais toujours dans le parc sont comptés à part comme un vivier mobilisable par
  redéploiement avant tout achat (« besoin net » ≤ « besoin brut »). Un taux de couverture global (jauge)
  rapporte les véhicules utilisables (affectés + vivier non affecté) au besoin total requis (chauffeurs +
  réserve). Aucun autre critère (kilométrage, usage partagé entre chauffeurs, budget) n'entre dans ce calcul,
  faute de règle communiquée au-delà de ces deux volets.
- **Limite cosmétique connue** : cette version de Streamlit (1.65) affiche le texte littéral « None » au lieu
  d'une cellule vide pour une date ou un nombre non renseigné dans un tableau modifiable (`st.data_editor`) —
  un comportement de la bibliothèque, pas une donnée manquante à corriger. Les tableaux en lecture seule
  (synthèse par véhicule, échéances de réforme) contournent ce rendu et affichent des cellules vides.

## Points de conception

- **Lecture robuste** : les tableaux sont localisés par recherche de titre de
  section plutôt que par numéro de ligne fixe — l'application continue de
  fonctionner si le classeur est régénéré avec quelques lignes en plus ou en moins.
- **Valeurs calculées** : le classeur est lu avec les valeurs mises en cache par
  Excel/LibreOffice (`data_only=True`). Si vous fournissez un fichier dont les
  formules n'ont jamais été recalculées (édité uniquement par un script sans
  ouverture dans Excel/LibreOffice), pensez à l'ouvrir et l'enregistrer une fois
  dans Excel, ou à le convertir via `soffice --headless --convert-to xlsx`.
- **Mise en cache** : `@st.cache_data` sur le parsing, `@st.cache_resource` sur le
  classeur ouvert — changer de fichier ou de filtre ne relit pas tout depuis zéro.
- **Couleurs** : la palette reprend celle du classeur Excel (navy / bleu / or /
  vert / rouge / ambre) pour une cohérence visuelle totale entre le fichier Excel
  et l'application — y compris sur les pages (Fonds revolving, Statistiques des
  compteurs) qui ne lisent pas ce classeur.

## Déploiement

Le projet est prêt pour [Streamlit Community Cloud](https://streamlit.io/cloud) :
poussez ce dossier sur un dépôt Git et pointez le déploiement vers `Home.py`.
