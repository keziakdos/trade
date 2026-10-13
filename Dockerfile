# Image Python
FROM python:3.9-slim

# Répertoire de travail
WORKDIR /app

# Dépendances système minimales (TA-Lib C retiré : inutilisé, RSI/MA calculés avec pandas)
RUN apt-get update && apt-get install -y \
    gcc \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copie et installation des requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copie du reste du projet
COPY . .

# Exposition du port
EXPOSE 5000

# Commande de lancement
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "run:app"]
