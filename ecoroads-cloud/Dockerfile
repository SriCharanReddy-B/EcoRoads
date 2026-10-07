# EcoRoads cloud API + municipal dashboard in one container.
# Build from the REPOSITORY ROOT (it needs both folders):
#   docker build -f ecoroads-cloud/Dockerfile -t ecoroads-cloud .
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY ecoroads-cloud/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY ecoroads-cloud/app ./ecoroads-cloud/app
COPY ecoroads-dashboard ./ecoroads-dashboard
# Without DATABASE_URL it falls back to SQLite in /data (use a volume for that)
ENV ECOROADS_DB=/data/ecoroads.db
WORKDIR /srv/ecoroads-cloud/app
EXPOSE 9000
# Hosts like Render tell the app which port to use via $PORT
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-9000} --proxy-headers --forwarded-allow-ips='*'"]
