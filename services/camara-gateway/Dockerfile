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
# Bake the consumer-facing profile contracts so GET /contracts serves them at
# runtime. Staged into the build context by `make stage-contracts` (the files
# live at the repo root, outside this context). See the self-describing
# contracts design doc.
COPY contracts/ /app/contracts/
# Writable store for the Asset Identity Map (network-authority GET/PUT /assets).
# Owned by app so a fresh named volume / PVC inherits writable ownership.
RUN mkdir -p /app/data && chown -R app /app/data
USER app
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
