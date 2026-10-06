FROM python:3.11-slim@sha256:0dd364ba7e10242f07755449e3a3d0e35f9efd987952737b90def6709ab0c5ce AS builder
WORKDIR /build
COPY requirements.txt constraints.txt ./
RUN pip install --prefix=/install -r requirements.txt -c constraints.txt

FROM python:3.11-slim@sha256:0dd364ba7e10242f07755449e3a3d0e35f9efd987952737b90def6709ab0c5ce
RUN useradd -r -u 1001 app
COPY --from=builder /install /usr/local
WORKDIR /app
COPY app/ app/
COPY env.contract.yaml /app/env.contract.yaml
COPY adapter.contract.yaml /app/adapter.contract.yaml
USER app
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
