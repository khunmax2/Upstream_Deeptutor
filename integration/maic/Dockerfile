# syntax=docker/dockerfile:1

# ---- Stage 1: Base ----
FROM node:22-alpine AS base

ARG ALPINE_MIRROR=""
ARG NPM_REGISTRY=""

RUN if [ -n "$ALPINE_MIRROR" ]; then \
      sed -i "s|dl-cdn.alpinelinux.org|$ALPINE_MIRROR|g" /etc/apk/repositories; \
    fi && \
    apk add --no-cache libc6-compat

RUN npm_registry="$NPM_REGISTRY"; \
    while [ "${npm_registry%/}" != "$npm_registry" ]; do \
      npm_registry="${npm_registry%/}"; \
    done; \
    if [ -n "$npm_registry" ]; then \
      export COREPACK_NPM_REGISTRY="$npm_registry"; \
    fi && \
    corepack enable && \
    corepack prepare pnpm@10.28.0 --activate

WORKDIR /app

# ---- Stage 2: Dependencies ----
FROM base AS deps

ARG NPM_REGISTRY

# Native build tools for sharp, @napi-rs/canvas
RUN apk add --no-cache python3 build-base g++ cairo-dev pango-dev jpeg-dev giflib-dev librsvg-dev

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY packages/ ./packages/
COPY scripts/ ./scripts/

RUN --mount=type=cache,id=pnpm-store,target=/root/.local/share/pnpm/store \
    npm_registry="$NPM_REGISTRY"; \
    while [ "${npm_registry%/}" != "$npm_registry" ]; do \
      npm_registry="${npm_registry%/}"; \
    done; \
    if [ -n "$npm_registry" ]; then \
      pnpm config set registry "$npm_registry"; \
    fi && \
    pnpm install --frozen-lockfile

# ---- Stage 3: Builder ----
FROM base AS builder

# The subpath this app is served under, when a reverse proxy routes a prefix
# to it rather than giving it a host of its own. Structural: Next generates
# every /_next/ asset URL from it, so it has to be known at build time and
# cannot be switched per request. Unset means "owns the domain root", which is
# every deployment that does not need this.
ARG NEXT_PUBLIC_BASE_PATH
ARG ALLOWED_FRAME_ANCESTORS
ARG NEXT_PUBLIC_PERSISTENCE
ARG NEXT_PUBLIC_PERSISTENCE_TOKEN
ARG NEXT_PUBLIC_PRO_WORKBENCH_ENABLED
ARG NEXT_PUBLIC_MAIC_EDITOR_ENABLED
ARG NEXT_PUBLIC_MAIC_EDITOR_RENDERER_ENABLED
ARG NEXT_PUBLIC_MAIC_PLAYBACK_RENDERER_ENABLED
ARG NEXT_PUBLIC_PI_CHAT_ENABLED
ARG NEXT_PUBLIC_SHOW_VOCATIONAL_TEST_UI
ARG NEXT_PUBLIC_ENABLE_VIDEO_EXPORT
ARG NEXT_PUBLIC_VIDEO_EXPORT_CTA_DESTINATION
ARG NEXT_PUBLIC_ENABLE_PPTX_IMPORT
ENV NEXT_PUBLIC_BASE_PATH=$NEXT_PUBLIC_BASE_PATH
ENV ALLOWED_FRAME_ANCESTORS=$ALLOWED_FRAME_ANCESTORS
ENV NEXT_PUBLIC_PERSISTENCE=$NEXT_PUBLIC_PERSISTENCE
ENV NEXT_PUBLIC_PERSISTENCE_TOKEN=$NEXT_PUBLIC_PERSISTENCE_TOKEN
ENV NEXT_PUBLIC_PRO_WORKBENCH_ENABLED=$NEXT_PUBLIC_PRO_WORKBENCH_ENABLED
ENV NEXT_PUBLIC_MAIC_EDITOR_ENABLED=$NEXT_PUBLIC_MAIC_EDITOR_ENABLED
ENV NEXT_PUBLIC_MAIC_EDITOR_RENDERER_ENABLED=$NEXT_PUBLIC_MAIC_EDITOR_RENDERER_ENABLED
ENV NEXT_PUBLIC_MAIC_PLAYBACK_RENDERER_ENABLED=$NEXT_PUBLIC_MAIC_PLAYBACK_RENDERER_ENABLED
ENV NEXT_PUBLIC_PI_CHAT_ENABLED=$NEXT_PUBLIC_PI_CHAT_ENABLED
ENV NEXT_PUBLIC_SHOW_VOCATIONAL_TEST_UI=$NEXT_PUBLIC_SHOW_VOCATIONAL_TEST_UI
ENV NEXT_PUBLIC_ENABLE_VIDEO_EXPORT=$NEXT_PUBLIC_ENABLE_VIDEO_EXPORT
ENV NEXT_PUBLIC_VIDEO_EXPORT_CTA_DESTINATION=$NEXT_PUBLIC_VIDEO_EXPORT_CTA_DESTINATION
ENV NEXT_PUBLIC_ENABLE_PPTX_IMPORT=$NEXT_PUBLIC_ENABLE_PPTX_IMPORT

COPY --from=deps /app/node_modules ./node_modules
COPY --from=deps /app/packages ./packages
COPY . .
COPY --from=deps /app/public/vendor ./public/vendor

RUN pnpm build

# ---- Stage 4: Runner ----
FROM node:22-alpine AS runner

ARG ALPINE_MIRROR=""

WORKDIR /app

ENV NODE_ENV=production
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

RUN if [ -n "$ALPINE_MIRROR" ]; then \
      cp /etc/apk/repositories /tmp/apk.repositories; \
      sed -i "s|dl-cdn.alpinelinux.org|$ALPINE_MIRROR|g" /etc/apk/repositories; \
    fi && \
    apk add --no-cache libc6-compat cairo pango jpeg giflib librsvg && \
    if [ -n "$ALPINE_MIRROR" ]; then \
      mv /tmp/apk.repositories /etc/apk/repositories; \
    fi

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

# Create the data directory as the runtime user before dropping privileges.
# docker-compose.yml mounts a named volume here, and Docker seeds a fresh named
# volume with the ownership of the image path it covers — so when that path does
# not exist in the image, the mount point is created root-owned and `nextjs`
# cannot write to its own data directory. Classrooms, materials and usage all
# land here, and every write fails with EACCES.
RUN mkdir -p /app/data && chown -R nextjs:nodejs /app/data

USER nextjs

EXPOSE 3000

CMD ["node", "server.js"]
