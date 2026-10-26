#!/bin/sh
# Runs once at container start (nginx image: /docker-entrypoint.d/). If no certificate was
# mounted at /etc/nginx/tls, make a self-signed one for this host, valid 365 days, so the
# site always runs over HTTPS. The key is created in the container, never kept in the image
# or the repository. For a real deployment mount cert.pem and key.pem instead.
set -eu
dir=/etc/nginx/tls
if [ -s "$dir/cert.pem" ] && [ -s "$dir/key.pem" ]; then
  echo "tls: using the mounted certificate"
  exit 0
fi
mkdir -p "$dir"
openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -subj "/CN=${TLS_HOSTNAME:-localhost}" \
  -addext "subjectAltName=DNS:${TLS_HOSTNAME:-localhost},DNS:localhost,IP:127.0.0.1" \
  -keyout "$dir/key.pem" -out "$dir/cert.pem" 2>/dev/null
chmod 600 "$dir/key.pem"
echo "tls: made a self-signed certificate for ${TLS_HOSTNAME:-localhost} (development only)"
