FROM python:3.11-slim

WORKDIR /app

COPY ../reranker/requirements.txt reranker_requirements.txt
COPY ../ingestion/requirements.txt ingestion_requirements.txt
COPY requirements.txt .

RUN pip install --no-cache-dir \
    -r reranker_requirements.txt \
    -r ingestion_requirements.txt \
    -r requirements.txt

COPY .. .

WORKDIR /app/trader

CMD ["python", "main.py"]
