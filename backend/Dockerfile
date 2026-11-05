FROM python:3.11-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*
RUN pip install emergentintegrations==0.2.0 --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/
# Installation des dépendances
COPY requirements.txt requirements.karaoke-text.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copie du code source
COPY . .

# Exposition du port backend par défaut de FastAPI
EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
