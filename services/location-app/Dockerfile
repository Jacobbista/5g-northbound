FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY entrypoint.sh /docker-entrypoint.d/40-render-env-config.sh
RUN chmod +x /docker-entrypoint.d/40-render-env-config.sh
EXPOSE 80
