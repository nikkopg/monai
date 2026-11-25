# Build stage — install all deps and produce the production build
FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
# A slow connection made npm ci die with EIDLETIMEOUT at npm's 5-minute
# default: wait up to 15 minutes per request and retry more before failing.
ENV NPM_CONFIG_FETCH_TIMEOUT=900000 \
    NPM_CONFIG_FETCH_RETRIES=5 \
    NPM_CONFIG_FETCH_RETRY_MAXTIMEOUT=120000
# Keep npm's download cache between builds (BuildKit cache mount), so a failed
# install on a flaky connection resumes from what it already fetched.
RUN --mount=type=cache,target=/root/.npm npm ci
COPY . .
RUN npm run build

# Run stage — ship the built app
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/package.json /app/package-lock.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/next.config.js ./next.config.js

EXPOSE 3001
CMD ["npm", "run", "start"]
