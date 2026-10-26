FROM node:24-alpine AS build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM nginx:1.27-alpine
# openssl: only to make a self-signed certificate when none is mounted (10-tls-cert.sh).
RUN apk add --no-cache openssl && rm /etc/nginx/conf.d/default.conf
COPY web/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY web/10-tls-cert.sh /docker-entrypoint.d/10-tls-cert.sh
COPY --from=build /web/dist /usr/share/nginx/html
ENV HTTPS_PORT=8443
EXPOSE 80 443
