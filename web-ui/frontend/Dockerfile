FROM node:20-bookworm-slim AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --legacy-peer-deps --no-audit --no-fund
RUN npm install @rollup/rollup-linux-x64-gnu@4.59.0 --no-save --legacy-peer-deps --no-audit --no-fund

COPY . .

ARG VITE_SERVER_URL=/api
ENV VITE_SERVER_URL=${VITE_SERVER_URL}

RUN npm run build

FROM node:20-bookworm-slim AS runtime

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --omit=dev --legacy-peer-deps --no-audit --no-fund

COPY --from=builder /app/dist ./dist
COPY server.js ./

EXPOSE 5000

CMD ["node", "server.js"]
