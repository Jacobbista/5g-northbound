FROM python:3.11-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

FROM python:3.11-slim
RUN useradd -r -u 1001 app && mkdir -p /app/data && chown app:app /app/data
COPY --from=builder /install /usr/local
WORKDIR /app
COPY app/ app/
COPY env.contract.yaml /app/env.contract.yaml
COPY adapter.contract.yaml /app/adapter.contract.yaml
# Bake the normative diagnostics vocabulary the adapter routes against. Staged
# into the build context by `make stage-contracts` (it lives at the repo root,
# outside this context). Single source of truth stays the repo root; the
# gateway publishes the same artifact via GET /contracts.
COPY contracts/ /app/contracts/
USER app
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
