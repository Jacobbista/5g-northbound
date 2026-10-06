# 1. Build the SPA bundle. Vite outputs to ../static (configured in vite.config.js),
#    which lives outside /fe - so we pick it up from /static in this stage.
FROM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293 AS frontend
WORKDIR /fe
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# 2. Install Python deps.
FROM python:3.11-slim@sha256:0dd364ba7e10242f07755449e3a3d0e35f9efd987952737b90def6709ab0c5ce AS pybuild
WORKDIR /build
COPY requirements.txt constraints.txt ./
RUN pip install --prefix=/install -r requirements.txt -c constraints.txt

# 3. Final image: Python runtime + built SPA served as static assets by FastAPI.
FROM python:3.11-slim@sha256:0dd364ba7e10242f07755449e3a3d0e35f9efd987952737b90def6709ab0c5ce
RUN useradd -r -u 1001 app
COPY --from=pybuild /install /usr/local
WORKDIR /app
COPY app/ app/
COPY env.contract.yaml /app/env.contract.yaml
COPY --from=frontend /static static/
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh && chown -R app /app/static
USER app
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
