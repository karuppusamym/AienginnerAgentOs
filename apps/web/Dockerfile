FROM node:22-alpine AS dependencies
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts

FROM node:22-alpine AS build
WORKDIR /app
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
COPY --from=dependencies /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/package-lock.json ./package-lock.json
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/.next ./.next
COPY --from=build /app/public ./public
RUN npm prune --omit=dev

# Same non-root / group-0 pattern as apps/api/Dockerfile — works unmodified
# under plain Docker/Kubernetes (fixed UID 1001) and under OpenShift's
# arbitrary-UID restricted SCC (group 0 stays writable either way).
RUN chown -R 1001:0 /app && chmod -R g=u /app
USER 1001:0

EXPOSE 3000
CMD ["npm", "run", "start"]
