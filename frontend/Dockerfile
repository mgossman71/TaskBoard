# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# TaskBoard web image (multi-stage)
#   deps    -> npm ci from the lockfile (reproducible)
#   test    -> runs typecheck + vitest (used by compose.test.yaml)
#   build   -> production Vite build
#   runtime -> unprivileged nginx serving static assets + reverse proxy (default)
# ---------------------------------------------------------------------------
ARG NODE_IMAGE=node:24.22.2-alpine
ARG NGINX_IMAGE=nginxinc/nginx-unprivileged:1.28.2-alpine

FROM ${NODE_IMAGE} AS deps
WORKDIR /app
COPY package.json package-lock.json .npmrc ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund

FROM deps AS test
COPY . .
CMD ["sh", "-c", "npm run typecheck && npm test"]

FROM deps AS build
COPY . .
RUN npm run build

FROM ${NGINX_IMAGE} AS runtime
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY nginx/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY nginx/proxy-headers.conf /etc/nginx/snippets/proxy-headers.conf
COPY --chmod=0755 nginx/10-taskboard.envsh /docker-entrypoint.d/10-taskboard.envsh
COPY --from=build /app/dist /usr/share/nginx/html
ENV API_UPSTREAM=api:8000 \
    MAX_UPLOAD_MB=10 \
    TRUSTED_PROXY_CIDRS=127.0.0.1/32 \
    NGINX_API_RATE=50r/s \
    NGINX_AUTH_RATE=10r/s \
    HSTS_ENABLED=false
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
