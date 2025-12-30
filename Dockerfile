# ===========================================
# ToitureAI - Dockerfile Production
# ===========================================

FROM python:3.11-slim

# Variables d'environnement
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_ENV=production \
    API_HOST=0.0.0.0 \
    API_PORT=8000

# Repertoire de travail
WORKDIR /app

# Installation des dependances systeme pour pycairo (requis par xhtml2pdf)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    pkg-config \
    libcairo2-dev \
    python3-dev \
    meson \
    ninja-build \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip tooling
RUN pip install --upgrade pip setuptools wheel

# Copie des requirements et installation
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Creer un utilisateur non-root
RUN groupadd -r toitureai && useradd -r -g toitureai toitureai

# Copie du code source
COPY --chown=toitureai:toitureai . .

# Changement vers l'utilisateur non-root
USER toitureai

# Exposition du port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Commande de demarrage
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
