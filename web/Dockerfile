# ── Stage 1: build (optional) ────────────────────────────────────────────────
# Use this stage if your frontend has a build step (Vite, React, Vue, etc.)
# Remove stages 1–2 and use the simpler form below if you have plain static files.
#
# FROM node:20-alpine AS builder
# WORKDIR /app
# COPY package*.json ./
# RUN npm ci
# COPY . .
# RUN npm run build
# # Build output goes to /app/dist

# ── Stage 2: serve with nginx ─────────────────────────────────────────────────
FROM nginx:alpine

# Copy built assets from the build stage:
# COPY --from=builder /app/dist /usr/share/nginx/html

# Or copy plain static files directly (no build step):
COPY static/ /usr/share/nginx/html/

COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
