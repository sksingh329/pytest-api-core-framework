#!/usr/bin/env bash
# =============================================================================
# deploy/scripts/init-certs.sh
#
# Run ONCE on the server to obtain the initial Let's Encrypt certificate.
# After this, certbot in the compose stack auto-renews every 12 h.
#
# Usage:
#   cd ~/pypi-deploy
#   cp .env.example .env && nano .env   # fill in DOMAIN and LETSENCRYPT_EMAIL
#   chmod +x scripts/init-certs.sh scripts/add-user.sh scripts/deploy.sh
#   ./scripts/init-certs.sh
# =============================================================================
set -euo pipefail

# ---- Load env ---------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: .env not found. Copy .env.example to .env and fill in values."
    exit 1
fi

# shellcheck source=/dev/null
source "$ENV_FILE"

: "${DOMAIN:?DOMAIN must be set in .env}"
: "${LETSENCRYPT_EMAIL:?LETSENCRYPT_EMAIL must be set in .env}"

info()    { echo -e "\033[0;34m[INFO]\033[0m  $*"; }
success() { echo -e "\033[0;32m[OK]\033[0m    $*"; }
error()   { echo -e "\033[0;31m[ERROR]\033[0m $*" >&2; exit 1; }

# ---- Create directories -----------------------------------------------------
info "Creating required directories..."
mkdir -p \
    "$SCRIPT_DIR/../data/packages" \
    "$SCRIPT_DIR/../data/auth" \
    "$SCRIPT_DIR/../certbot/www" \
    "$SCRIPT_DIR/../certbot/conf"

# ---- Create placeholder htpasswd if not present (so nginx starts) -----------
HTPASSWD="$SCRIPT_DIR/../data/auth/htpasswd.txt"
if [[ ! -f "$HTPASSWD" ]]; then
    info "Creating empty htpasswd file (add users with scripts/add-user.sh)..."
    touch "$HTPASSWD"
fi

# ---- Substitute domain into nginx config ------------------------------------
info "Templating nginx config for domain: $DOMAIN..."
sed "s/\${DOMAIN}/$DOMAIN/g" \
    "$SCRIPT_DIR/../nginx/conf.d/pypi.conf" \
    > "$SCRIPT_DIR/../nginx/conf.d/pypi.conf.rendered"
mv "$SCRIPT_DIR/../nginx/conf.d/pypi.conf.rendered" \
   "$SCRIPT_DIR/../nginx/conf.d/pypi.conf"

# ---- Start nginx on HTTP only (needed for ACME challenge) -------------------
info "Starting nginx temporarily (HTTP only) for ACME challenge..."

# Temporarily use a minimal HTTP-only nginx config
cat > "$SCRIPT_DIR/../nginx/conf.d/acme-only.conf" <<NGINX
server {
    listen 80;
    server_name $DOMAIN;
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }
    location / { return 200 'ready'; }
}
NGINX

# Backup the real config and use only the acme config
mv "$SCRIPT_DIR/../nginx/conf.d/pypi.conf" \
   "$SCRIPT_DIR/../nginx/conf.d/pypi.conf.bak"

docker compose -f "$SCRIPT_DIR/../docker-compose.yml" \
    up -d nginx --no-deps

sleep 3

# ---- Obtain certificate -----------------------------------------------------
info "Requesting Let's Encrypt certificate for $DOMAIN..."
docker compose -f "$SCRIPT_DIR/../docker-compose.yml" run --rm certbot \
    certonly \
    --webroot \
    --webroot-path /var/www/certbot \
    --email "$LETSENCRYPT_EMAIL" \
    --agree-tos \
    --no-eff-email \
    --domains "$DOMAIN"

# ---- Restore full nginx config ----------------------------------------------
mv "$SCRIPT_DIR/../nginx/conf.d/pypi.conf.bak" \
   "$SCRIPT_DIR/../nginx/conf.d/pypi.conf"
rm -f "$SCRIPT_DIR/../nginx/conf.d/acme-only.conf"

# ---- Bring up full stack -----------------------------------------------------
info "Bringing up full stack..."
docker compose -f "$SCRIPT_DIR/../docker-compose.yml" up -d

success "Done! pypiserver is live at https://$DOMAIN"
echo ""
echo "Next steps:"
echo "  1. Add your first user:  ./scripts/add-user.sh <username>"
echo "  2. Configure pip:        see client-config/pip.conf"
echo "  3. Publish a package:    twine upload --repository-url https://$DOMAIN dist/*"
