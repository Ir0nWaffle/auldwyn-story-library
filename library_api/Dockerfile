FROM python:3.12-slim

RUN useradd --create-home --uid 1000 api

WORKDIR /app
COPY library_api/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY common ./common
COPY library_api ./library_api
COPY seed ./seed

RUN chmod +x /app/common/assets/kepubify-linux-64bit \
    && chown -R api:api /app

# Created (and owned by `api`) here, before the VOLUME line, so a fresh
# named volume inherits this ownership on first mount instead of coming
# up root-owned and unwritable by the non-root user below. This
# container now writes (POST /internal/ingest), not just reads, so the
# volume is read-write -- see docker-compose.yml.
RUN mkdir -p /data && chown api:api /data
ENV LIBRARY_DATA_DIR=/data
VOLUME /data

USER api
WORKDIR /app/library_api
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
