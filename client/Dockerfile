# ==============================================================
# SecureCore IDS — Frontend Docker Image
# Multi-stage build: Node (build) → Nginx (serve)
# ==============================================================

# ---------- Stage 1: Build ----------
FROM node:20-alpine AS build

WORKDIR /app

# Install dependencies first (layer caching)
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts

# Build-time env vars (override at build: --build-arg VITE_API_URL=...)
ARG VITE_API_URL=http://localhost:5000
ARG VITE_WS_URL=ws://localhost:5000
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_WS_URL=$VITE_WS_URL

# Copy source and build
COPY . .
RUN npm run build

# ---------- Stage 2: Serve ----------
FROM nginx:1.25-alpine

# Remove default nginx config
RUN rm /etc/nginx/conf.d/default.conf

# Copy our SPA nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built assets from Stage 1
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://localhost/health || exit 1

CMD ["nginx", "-g", "daemon off;"]
