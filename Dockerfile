# Google Cloud Run：容器需監聽 $PORT（預設 8080）
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 本機開發可 COPY credentials.json；雲端請用 Secret 掛載 token，勿把憑證打進映像
EXPOSE 8080

CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 8 --timeout 0 webhook_app:app"]
