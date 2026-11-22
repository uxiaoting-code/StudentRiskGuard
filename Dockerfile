FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    API_PORT=8000 \
    RISKGUARD_API_URL=http://127.0.0.1:8000 \
    AUTH_DB_PATH=/tmp/studentriskguard/auth.db

WORKDIR /app

RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --create-home --shell /bin/bash appuser

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY . .
RUN python -m pip install --no-deps -e . \
    && mkdir -p /tmp/studentriskguard \
    && chown -R appuser:appuser /app /tmp/studentriskguard

USER appuser

EXPOSE 7860

CMD ["bash", "start.sh"]
