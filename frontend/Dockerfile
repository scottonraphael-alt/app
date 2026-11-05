FROM node:20-slim AS build
WORKDIR /app

# A committed lockfile is mandatory: do not resolve dependencies during deployment.
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund

COPY public ./public
COPY src ./src
COPY plugins ./plugins
COPY scripts ./scripts
COPY craco.config.js postcss.config.js tailwind.config.js jsconfig.json ./

ARG REACT_APP_BACKEND_URL
ENV REACT_APP_BACKEND_URL=$REACT_APP_BACKEND_URL
ENV GENERATE_SOURCEMAP=false
# Nécessaire pour une CSP sans 'unsafe-inline' sur les scripts
ENV INLINE_RUNTIME_CHUNK=false

RUN --mount=type=cache,id=iris-webpack-cache,target=/app/node_modules/.cache,sharing=locked npm run build

FROM nginx:alpine
COPY --from=build /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
