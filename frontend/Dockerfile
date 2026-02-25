# =============================================================================
# Sentinel-KE Frontend Dockerfile
#
# Build strategy (BUILD ONCE + hot-reload):
#   docker compose build  → npm install baked into image layer
#   docker compose up     → volume-mounts ./frontend:/usr/src/app
#                           Vite HMR handles every file change without rebuild
#
# node_modules are kept INSIDE the container (anonymous volume) so the
# host's node_modules (if any) never shadow the container's.
# =============================================================================
FROM node:20-alpine

WORKDIR /usr/src/app

# Install deps first (layer cached until package.json changes)
COPY package.json package-lock.json* ./
RUN npm ci --prefer-offline

# Copy source (only relevant for production builds; dev uses volume mount)
COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
