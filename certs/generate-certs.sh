#!/usr/bin/env bash
set -e

HOST_IP="$1"

if [ -z "$HOST_IP" ]; then
  echo "Usage: ./generate-certs.sh <HOST_IP>"
  exit 1
fi

# Resolve base directory (important when script is run from anywhere)
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"

CERTS_DIR="$BASE_DIR"
CA_DIR="$CERTS_DIR/ca"
ES_DIR="$CERTS_DIR/elasticsearch"
KIBANA_DIR="$CERTS_DIR/kibana"
LOGSTASH_DIR="$CERTS_DIR/logstash"

echo "[+] Creating certificate directories"
mkdir -p "$CA_DIR" "$ES_DIR" "$KIBANA_DIR" "$LOGSTASH_DIR"


# Generate CA

echo "[+] Generating CA"

openssl genrsa -out "$CA_DIR/ca.key" 4096

openssl req -x509 -new -nodes \
  -key "$CA_DIR/ca.key" \
  -sha256 \
  -days 3650 \
  -subj "/C=IN/ST=Maharashtra/L=Mumbai/O=TLSOC/OU=Security/CN=TLSOC-CA" \
  -out "$CA_DIR/ca.crt"

##################################
# Function to generate certs
##################################
gen_cert () {
  NAME="$1"
  CN="$2"
  DIR="$CERTS_DIR/$NAME"

  echo "[+] Generating cert for $NAME"

  openssl genrsa -out "$DIR/$NAME.key" 2048

  openssl req -new \
    -key "$DIR/$NAME.key" \
    -subj "/CN=$CN" \
    -out "$DIR/$NAME.csr"

  cat > "$DIR/$NAME.ext" <<EOF
subjectAltName = DNS:$NAME,IP:$HOST_IP
extendedKeyUsage = serverAuth
EOF

  openssl x509 -req \
    -in "$DIR/$NAME.csr" \
    -CA "$CA_DIR/ca.crt" \
    -CAkey "$CA_DIR/ca.key" \
    -CAcreateserial \
    -out "$DIR/$NAME.crt" \
    -days 825 \
    -sha256 \
    -extfile "$DIR/$NAME.ext"
}


# Generate service certs

gen_cert elasticsearch elasticsearch
gen_cert kibana kibana
gen_cert logstash logstash

# Permissions (safe defaults)

chmod 600 "$CA_DIR/ca.key" "$ES_DIR/"*.key "$KIBANA_DIR/"*.key "$LOGSTASH_DIR/"*.key
chmod 644 "$CA_DIR/ca.crt" "$ES_DIR/"*.crt "$KIBANA_DIR/"*.crt "$LOGSTASH_DIR/"*.crt

echo "Certificates generated successfully"

