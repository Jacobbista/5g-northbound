# 1. Build the SPA bundle. Vite outputs to ../static (configured in vite.config.js),
#    which lives outside /fe - so we pick it up from /static in this stage.
FROM node:20-alpine AS frontend
WORKDIR /fe
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# 2. Install Python deps.
FROM python:3.11-slim AS pybuild
WORKDIR /build
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

# 3. Final image: Python runtime + built SPA served as static assets by FastAPI.
FROM python:3.11-slim
RUN useradd -r -u 1001 app
COPY --from=pybuild /install /usr/local
WORKDIR /app
COPY app/ app/
COPY --from=frontend /static static/
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh && chown -R app /app/static
USER app
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
