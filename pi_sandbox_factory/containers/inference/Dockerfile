FROM docker.io/library/node:24-bookworm-slim@sha256:01d566e8d94d8c619591d78652babfccd3c6992a3dffa9ed5ab39e11cf6c70e9
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts --no-audit --no-fund && npm cache clean --force
COPY broker.mjs credentials.mjs ./
USER node
CMD ["node", "/app/broker.mjs", "/config/routes.json", "/private/credentials.json", "/run/inference/proxy.sock"]
