# =============================================================================
# SOLVEREIGN Frontend (Next.js) - Docker Development Build
# =============================================================================
# This Dockerfile is for local development/staging.
# For production, use a multi-stage build with standalone output.
# =============================================================================

FROM node:20-alpine

WORKDIR /app

# Install dependencies first (cache layer)
COPY package.json package-lock.json* ./
RUN npm ci --prefer-offline --no-audit

# Copy source
COPY . .

# Set BACKEND_URL for build-time (Next.js config reads this during build)
ENV BACKEND_URL=http://api:8000

# Build the application
RUN npm run build

# Expose port 3000
EXPOSE 3000

# Set production environment
ENV NODE_ENV=production
ENV HOSTNAME=0.0.0.0

# Start the production server
CMD ["npm", "start"]
