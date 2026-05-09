# Build-only image — produces /app/dist for Caddy to serve.
FROM node:20-alpine AS builder
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

# Final stage: nothing but the dist tree, so this image can act as a
# build artifact that gets copied into the Caddy image at compose time.
FROM scratch AS dist
COPY --from=builder /app/dist /dist
