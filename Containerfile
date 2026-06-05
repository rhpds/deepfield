FROM registry.access.redhat.com/ubi9/python-311:latest

WORKDIR /opt/app-root/src

COPY backend/pyproject.toml .
RUN pip install --no-cache-dir pydantic fastapi uvicorn httpx pyyaml asyncpg \
    "celery[redis]" kafka-python-ng

COPY backend/app/ app/
COPY frontend/dist/ static/

EXPOSE 8099

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8099/health')"

USER 1001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8099"]
