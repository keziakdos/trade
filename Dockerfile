# Image Python
FROM python:3.9-slim

# Répertoire de travail
WORKDIR /app

# Installation des dépendances système + TA-Lib C Library
# On télécharge et compile TA-Lib avant d'installer les requirements Python
RUN apt-get update && apt-get install -y \
    gcc \
    build-essential \
    python3-dev \
    wget \
    tar \
    && rm -rf /var/lib/apt/lists/* \
    && wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz \
    && tar -xzf ta-lib-0.4.0-src.tar.gz \
    && cd ta-lib/ \
    && ./configure --prefix=/usr \
    && make \
    && make install \
    && cd .. \
    && rm -rf ta-lib ta-lib-0.4.0-src.tar.gz

# Copie et installation des requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copie du reste du projet
COPY . .

# Exposition du port
EXPOSE 5000

# Commande de lancement
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "run:app"]
