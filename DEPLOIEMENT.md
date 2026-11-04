# Mise en service et exploitation — Tableau de bord AER

## 1. Mise à jour sur Streamlit Cloud (procédure immédiate)

L'application est désormais **fermée par défaut** : sans compte déclaré, elle affiche un écran
« configuration requise ». Respectez donc cet ordre.

1. **Générer l'empreinte de votre mot de passe** (sur votre ordinateur, dans le dossier du projet) :
   ```bash
   python scripts/generer_mot_de_passe.py
   ```
   Le script demande l'identifiant, le nom, le rôle et le mot de passe (12 caractères minimum), puis
   affiche un bloc `[auth.users.…]`. Le mot de passe lui-même n'est jamais enregistré.
2. **Déclarer les comptes AVANT de publier le code** : sur share.streamlit.io → votre application →
   *Manage app* → *Settings* → *Secrets*, collez le ou les blocs (modèle : `.streamlit/secrets.example.toml`),
   puis *Save*. Créez au minimum un compte `admin`.
3. **Publier le code** :
   ```bash
   git add Home.py README.md DEPLOIEMENT.md requirements.txt packages.txt Dockerfile docker-compose.yml \
           .gitignore .streamlit/config.toml .streamlit/secrets.example.toml .github deploiement scripts tests \
           pages utils data/parametres_paie_aer.json data/budget_sdmse_2027.csv
   git commit -m "Version professionnelle : accès, stockage, plaidoyer, budget, alertes, supervision, recettes"
   git push
   ```
4. **Vérifier** : l'écran de connexion s'affiche ; connectez-vous ; ouvrez *Administration*.

### Rôles

| Rôle | Consultation | Modification des registres | Paie | Administration |
|---|---|---|---|---|
| `admin` | tout | oui | oui | oui |
| `direction` | tout | oui | oui | non |
| `drh` | tout | oui | oui | non |
| `sdmse` | tout sauf paie | oui | non | non |
| `lecteur` | tout sauf paie | non | non | non |

### Attention : stockage sur Streamlit Community Cloud

Sans base externe, les registres sont enregistrés dans un fichier SQLite **effacé à chaque redémarrage**
de l'application (mise à jour du code, mise en veille prolongée). Deux solutions :

- **Immédiate** : après chaque séance de saisie, *Administration* → *Préparer la sauvegarde* →
  télécharger ; après un redémarrage, *Restaurer cette sauvegarde*.
- **Durable** : déclarer une base PostgreSQL dans les secrets :
  ```toml
  [database]
  url = "postgresql+psycopg2://UTILISATEUR:MOT_DE_PASSE@HOTE:5432/aer"
  ```
  La base doit être joignable depuis Internet (Data Center de l'AER avec ouverture contrôlée, ou
  prestataire). Les tables sont créées automatiquement au premier lancement.

## 2. Hébergement sur le Data Center de l'AER (recommandé à terme)

Avantages : données hébergées au Cameroun (loi n° 2024/017), plus de traceurs tiers de Streamlit
Cloud, base PostgreSQL durable, en-têtes de sécurité (HSTS…), nom de domaine de l'AER.

Prérequis : un serveur Linux avec Docker et Docker Compose, un nom de domaine pointant vers ce
serveur (ex. `tableau-de-bord.aer.cm`), ports 80/443 ouverts.

```bash
git clone https://github.com/aimethmbog1/aer-dashboard.git && cd aer-dashboard
echo "POSTGRES_PASSWORD=un-mot-de-passe-long" > .env
cp .streamlit/secrets.example.toml .streamlit/secrets.toml   # puis compléter : comptes + [database]
#   [database] url = "postgresql+psycopg2://aer:un-mot-de-passe-long@base:5432/aer"
nano deploiement/Caddyfile                                    # remplacer le nom de domaine
docker compose up -d --build
```

- Certificat HTTPS : obtenu et renouvelé automatiquement par Caddy.
- Mise à jour : `git pull && docker compose up -d --build`.
- Sauvegarde de la base : `docker compose exec base pg_dump -U aer aer > sauvegarde_$(date +%F).sql`
  (à planifier chaque nuit), en plus de la sauvegarde Excel de la page Administration.

## 3. Options facultatives (secrets)

- `[smtp]` : envoi du récapitulatif des alertes par courriel (page *Alertes*).
- `[mentions]` : responsable du traitement, contact, durée de conservation (page *Mentions et confidentialité*).

## 4. Tests

```bash
pip install -r requirements.txt pytest
pytest -q tests
```
Les tests vérifient que chaque page s'exécute sans erreur, que l'accès est bien protégé, que la paie
est interdite au rôle `lecteur` et que le moteur de paie donne les montants de référence. Ils sont
lancés automatiquement par GitHub à chaque `git push` (onglet *Actions* du dépôt).

## 5. Versions

Les versions des bibliothèques sont **figées** dans `requirements.txt`. Pour monter de version :
modifier le fichier, lancer `pytest`, publier seulement si tout passe.
