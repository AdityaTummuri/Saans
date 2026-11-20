FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

# Dependencies first so this layer is cached between code changes.
COPY pyproject.toml README.md LICENSE ./
COPY app ./app
RUN pip install -e . && rm -rf /root/.cache

COPY fixtures ./fixtures

# Run as an unprivileged user.
RUN useradd --system --uid 10001 --no-create-home saans \
    && chown -R saans:saans /srv
USER saans

ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --no-server-header"]
