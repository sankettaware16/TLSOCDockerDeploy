#!/usr/bin/env bash
set -e

HOST_IP=$1

if [ -z "$HOST_IP" ]; then
  echo "Usage: ./generate-certs.sh <HOST_IP>"
  exit 1
fi

echo "[+] Generating CA"
openssl genrsa -out certs/ca/ca.key 4096
openssl req -x509 -new -nodes \
  -key certs/ca/ca.key \
  -sha256 -days 3650 \
  -subj "/CN=TLSOC-CA" \
  -out certs/ca/ca.crt

gen_cert () {
  NAME=$1
  CN=$2

  echo "[+] Generating cert for $NAME"

  openssl genrsa -out certs/$NAME/$NAME.key 4096

  openssl req -new \
    -key certs/$NAME/$NAME.key \
    -subj "/CN=$CN" \
    -out certs/$NAME/$NAME.csr

  openssl x509 -req \
    -in certs/$NAME/$NAME.csr \
    -CA certs/ca/ca.crt \
    -CAkey certs/ca/ca.key \
    -CAcreateserial \
    -out certs/$NAME/$NAME.crt \
    -days 825 -sha256 \
    -extfile <(cat <<EXT
subjectAltName = DNS:$NAME,IP:$HOST_IP
EXT
)
}

gen_cert elasticsearch elasticsearch
gen_cert kibana kibana
gen_cert logstash logstash

echo "[✓] Certificates generated successfully"
