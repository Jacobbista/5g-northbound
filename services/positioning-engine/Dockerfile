FROM python:3.11-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

FROM python:3.11-slim
RUN useradd -r -u 1001 app
COPY --from=builder /install /usr/local
WORKDIR /app
COPY app/ app/
COPY env.contract.yaml /app/env.contract.yaml
# Normative accuracy-class bands, read when a source reports no per-fix
# accuracy. Lives at the repo root, outside this build context, so
# `make stage-contracts` copies it in before the build.
COPY contracts/ /app/contracts/
# Writable dir for the persisted blueprint (GET/PUT /blueprint). In the cluster
# mount a PVC here; the directory must be owned by the non-root app user.
RUN mkdir -p /app/data && chown -R app /app/data
USER app
EXPOSE 8080
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
