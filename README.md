# ToitureAI - API Python

Migration complète des workflows n8n vers une application Python/FastAPI moderne.

## Vue d'ensemble

ToitureAI est une application de gestion de leads et devis pour entreprises de toiture. Cette API remplace les 6 workflows n8n par une solution Python robuste, testable et maintenable.

### Workflows migrés

| # | Workflow | Statut | Endpoint |
|---|----------|--------|----------|
| 1 | Lead Generation & Qualification AI | ✅ Terminé | `POST /api/v1/leads/webhook` |
| 2 | Devis & Facturation | 🔄 En cours | `POST /api/v1/devis/generate` |
| 3 | Rapport Mensuel PDF | ⏳ Planifié | Tâche planifiée |
| 4 | Lead Tracking | ✅ Terminé | `GET /api/v1/tracking/track-lead` |
| 5 | DocuSeal Signature | ⏳ Planifié | `POST /api/v1/docuseal/webhook` |
| 6 | Error Handler | ✅ Intégré | Middleware global |

## Stack technique

- **Framework**: FastAPI 0.115+
- **Validation**: Pydantic v2
- **Base de données**: Supabase (PostgreSQL)
- **IA**: OpenAI GPT-4o-mini
- **Email**: SendGrid
- **PDF**: WeasyPrint
- **Tests**: pytest
- **Déploiement**: Docker / Render / Fly.io

## Installation

### Prérequis

- Python 3.11+
- pip ou poetry

### Installation locale

```bash
# Cloner le repo
git clone https://github.com/votre-org/toitureai-api.git
cd toitureai-api

# Créer l'environnement virtuel
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou
.\venv\Scripts\activate  # Windows

# Installer les dépendances
pip install -r requirements.txt

# Copier et configurer les variables d'environnement
cp .env.example .env
# Éditer .env avec vos clés API
```

### Lancement

```bash
# Mode développement avec rechargement automatique
uvicorn app.main:app --reload --port 8000

# Mode production
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

L'API sera disponible sur `http://localhost:8000`

- Documentation Swagger: `http://localhost:8000/docs`
- Documentation ReDoc: `http://localhost:8000/redoc`

## Configuration

Créez un fichier `.env` basé sur `.env.example`:

```env
# Obligatoire
WEBHOOK_SECRET=votre_secret_webhook_32_caracteres_minimum
TRACKING_SECRET=votre_secret_tracking_32_caracteres_min
SUPABASE_URL=https://votre-projet.supabase.co
SUPABASE_KEY=votre_cle_anon_supabase
OPENAI_API_KEY=sk-votre_cle_openai
SENDGRID_API_KEY=SG.votre_cle_sendgrid

# Optionnel
APP_ENV=development
DEBUG=true
ADMIN_EMAIL=admin@example.com
HOT_LEAD_THRESHOLD=70
```

## Endpoints API

### Workflow 1 - Lead Generation

```bash
# Créer un nouveau lead
curl -X POST http://localhost:8000/api/v1/leads/webhook \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: votre_secret" \
  -d '{
    "nom": "Dupont",
    "prenom": "Jean",
    "email": "jean.dupont@example.com",
    "telephone": "06 12 34 56 78",
    "typeDeProjet": "Rénovation complète",
    "adresse": "123 Rue de la Paix",
    "ville": "Paris",
    "codePostal": "75001",
    "surface": "120",
    "budget": "15000",
    "rgpd": true
  }'
```

### Workflow 4 - Lead Tracking

Les liens de tracking sont générés automatiquement et inclus dans les emails:

```
# Tracking ouverture (pixel 1x1)
GET /api/v1/tracking/track-lead?lead_id=UUID&type=open&s=SIGNATURE

# Tracking clic (page de confirmation)
GET /api/v1/tracking/track-lead?lead_id=UUID&type=click&s=SIGNATURE
```

### Health Checks

```bash
# Status général
curl http://localhost:8000/

# Health check détaillé
curl http://localhost:8000/health

# Readiness check
curl http://localhost:8000/ready
```

## Tests

```bash
# Lancer tous les tests
pytest

# Avec couverture
pytest --cov=app --cov-report=html

# Tests spécifiques
pytest tests/test_lead_webhook.py -v

# Tests par marker
pytest -m security
pytest -m "not slow"
```

## Déploiement

### Docker

```bash
# Build
docker build -t toitureai-api .

# Run
docker run -p 8000:8000 --env-file .env toitureai-api
```

### Render

1. Connectez votre repo GitHub à Render
2. Créez un nouveau Web Service
3. Configuration:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Ajoutez les variables d'environnement dans le dashboard Render

### Fly.io

```bash
# Installation de flyctl
curl -L https://fly.io/install.sh | sh

# Déploiement
fly launch
fly secrets set WEBHOOK_SECRET=xxx SUPABASE_URL=xxx ...
fly deploy
```

## Structure du projet

```
toitureai-api/
├── app/
│   ├── main.py              # Point d'entrée FastAPI
│   ├── api/
│   │   ├── lead_webhook.py  # Workflow 1
│   │   ├── tracking.py      # Workflow 4
│   │   ├── devis_webhook.py # Workflow 2
│   │   └── ...
│   ├── models/
│   │   └── lead.py          # Schémas Pydantic
│   ├── services/
│   │   ├── ai_qualification.py
│   │   ├── email_service.py
│   │   └── hmac_service.py
│   ├── utils/
│   │   └── validators.py
│   ├── tasks/
│   │   └── rapport_mensuel.py
│   └── core/
│       ├── config.py        # Settings Pydantic
│       ├── database.py      # Client Supabase
│       └── error_handler.py # Workflow 6
├── tests/
│   ├── conftest.py
│   └── test_lead_webhook.py
├── templates/               # Templates HTML emails
├── requirements.txt
├── Dockerfile
├── .env.example
└── README.md
```

## Sécurité

- **Authentification webhook**: Header `X-Webhook-Secret` validé sur tous les endpoints
- **HMAC tracking**: Signatures SHA-256 pour les liens de tracking
- **Rate limiting**: À implémenter selon besoin (recommandé: slowapi)
- **Validation**: Pydantic v2 avec validation stricte
- **Secrets**: Variables d'environnement, jamais en dur

## Contribution

1. Fork le repo
2. Créer une branche feature (`git checkout -b feature/ma-feature`)
3. Commit (`git commit -am 'Ajout de ma feature'`)
4. Push (`git push origin feature/ma-feature`)
5. Créer une Pull Request

## Support

- Email: support@toitureai.fr
- Issues: GitHub Issues

## Licence

Propriétaire - ToitureAI © 2024
