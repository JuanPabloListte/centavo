# La API de Centavo. Se construye desde la raíz del repositorio para poder copiar
# db/: tools.migrar busca las migraciones en /db.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app

COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY db /db
COPY api/app ./app
COPY api/tools ./tools

# Sin root: la API no escribe nada dentro del contenedor.
RUN useradd --create-home --uid 10001 centavo
USER centavo

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/salud', timeout=2)"

# Primero las migraciones, que son idempotentes, y después la API. Escucha en
# todas las interfaces del CONTENEDOR para que la web la alcance por la red
# interna de Compose; al host no se publica.
CMD ["sh", "-c", "python -m tools.migrar && exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"]
