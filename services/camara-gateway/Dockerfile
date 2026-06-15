FROM python:3.11-slim AS builder
WORKDIR /build
COPY pyproject.toml .
COPY app/ app/
# Build + install the app and its runtime deps (no dev extras) into an isolated prefix.
RUN pip install --prefix=/install .

FROM python:3.11-slim
RUN useradd -r -u 1001 app
COPY --from=builder /install /usr/local
# Bake the env contract so GET /contract can serve it at runtime.
COPY env.contract.yaml /app/env.contract.yaml
USER app
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
