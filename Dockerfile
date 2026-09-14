FROM python:3.12.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt requirements-dev.txt ./
ARG INSTALL_DEV=false
RUN if [ "$INSTALL_DEV" = "true" ]; then pip install -r requirements-dev.txt; else pip install -r requirements.txt; fi \
    && groupadd --gid 10001 spicy \
    && useradd --uid 10001 --gid spicy --no-create-home spicy
COPY --chown=spicy:spicy . .
RUN mkdir -p /app/staticfiles && chown spicy:spicy /app/staticfiles
USER spicy
EXPOSE 8000
CMD ["sh", "deploy/start.sh"]

