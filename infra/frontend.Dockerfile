FROM node:24-alpine AS builder
WORKDIR /frontend
COPY frontend/package*.json frontend/.npmrc ./
RUN npm ci
COPY frontend/ ./
ARG VITE_API_URL=/api
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build
FROM nginx:alpine
COPY --from=builder /frontend/dist /usr/share/nginx/html
COPY infra/nginx/dev.conf /etc/nginx/conf.d/default.conf
