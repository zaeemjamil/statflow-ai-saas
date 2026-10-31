FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# These are read at BUILD time. Keep the upload limits equal to the backend's.
ARG BACKEND_URL=http://backend:8000
ARG NEXT_PUBLIC_MAX_CSV_UPLOAD_MB=25
ARG NEXT_PUBLIC_MAX_XLSX_UPLOAD_MB=10
ENV BACKEND_URL=$BACKEND_URL \
    NEXT_PUBLIC_MAX_CSV_UPLOAD_MB=$NEXT_PUBLIC_MAX_CSV_UPLOAD_MB \
    NEXT_PUBLIC_MAX_XLSX_UPLOAD_MB=$NEXT_PUBLIC_MAX_XLSX_UPLOAD_MB \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
# Owned by the runtime user: Next.js writes its cache under .next/ while running.
COPY --chown=node:node --from=build /app ./
USER node
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD wget -qO- http://127.0.0.1:3000/login >/dev/null || exit 1
CMD ["npm", "run", "start"]
