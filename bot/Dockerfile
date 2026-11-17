FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src \
    DATA_DIR=/data

RUN groupadd --gid 10001 bot \
 && useradd --uid 10001 --gid bot --no-create-home --shell /usr/sbin/nologin bot

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
RUN mkdir -p /data && chown -R bot:bot /data /app

USER bot
VOLUME ["/data"]

HEALTHCHECK --interval=5m --timeout=15s --start-period=2m --retries=3 \
  CMD ["python", "-m", "pasito_bot.health"]

CMD ["python", "-m", "pasito_bot", "run"]
