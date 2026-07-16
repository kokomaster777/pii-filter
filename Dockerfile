FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Прогрев весов Natasha в образ
RUN python -c "from natasha import NewsEmbedding, NewsNERTagger; NewsNERTagger(NewsEmbedding())"
COPY app ./app
EXPOSE 8010
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
