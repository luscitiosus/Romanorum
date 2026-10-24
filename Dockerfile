FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Descarga las 18 ediciones de BIA (~60 MB de XML) y crea data/romanlaw.db
RUN python ingest.py && rm -rf data/raw
ENV PORT=8000
EXPOSE 8000
CMD ["python", "server.py"]
