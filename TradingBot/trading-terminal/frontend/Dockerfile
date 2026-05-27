# ── Stage 1: Builder ──
FROM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci --frozen-lockfile

COPY . .

# Build with mock data disabled so the container talks to the real backend
ARG VITE_API_BASE_URL=http://trading-terminal-backend:8000
ARG VITE_WS_URL=ws://trading-terminal-backend:8000
ARG VITE_MOCK_DATA=false
ARG VITE_ENV=production

RUN VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_WS_URL=$VITE_WS_URL \
    VITE_MOCK_DATA=$VITE_MOCK_DATA \
    VITE_ENV=$VITE_ENV \
    npm run build

# ── Stage 2: nginx ──
FROM nginx:1.27-alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY infra/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD wget -qO- http://localhost/health || exit 1

CMD ["nginx", "-g", "daemon off;"]
