#!/usr/bin/env bash
# =============================================================================
# deploy/scripts/add-user.sh
#
# Add or update a pypiserver user in htpasswd.txt using bcrypt hashing.
# Requires: apache2-utils (Debian/Ubuntu) or httpd-tools (RHEL/CentOS)
#           OR uses htpasswd bundled inside the nginx Docker image.
#
# Usage:
#   ./scripts/add-user.sh alice          # add/update user 'alice'
#   ./scripts/add-user.sh alice --delete # remove user 'alice'
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HTPASSWD_FILE="$SCRIPT_DIR/../data/auth/htpasswd.txt"

info()    { echo -e "\033[0;34m[INFO]\033[0m  $*"; }
success() { echo -e "\033[0;32m[OK]\033[0m    $*"; }
error()   { echo -e "\033[0;31m[ERROR]\033[0m $*" >&2; exit 1; }

[[ $# -lt 1 ]] && { echo "Usage: $0 <username> [--delete]"; exit 1; }

USERNAME="$1"
ACTION="${2:-}"

mkdir -p "$(dirname "$HTPASSWD_FILE")"

if [[ "$ACTION" == "--delete" ]]; then
    if command -v htpasswd &>/dev/null; then
        htpasswd -D "$HTPASSWD_FILE" "$USERNAME"
    else
        # Use htpasswd from nginx container
        docker run --rm \
            -v "$(realpath "$HTPASSWD_FILE"):/auth/htpasswd.txt" \
            nginx:1.27-alpine \
            htpasswd -D /auth/htpasswd.txt "$USERNAME"
    fi
    success "User '$USERNAME' removed."
    exit 0
fi

info "Adding/updating user '$USERNAME' (bcrypt)..."

if command -v htpasswd &>/dev/null; then
    # -B = bcrypt, -C 12 = cost factor (increase for more security, decrease for speed)
    htpasswd -B -C 12 "$HTPASSWD_FILE" "$USERNAME"
else
    # No htpasswd locally — use the nginx image which ships it
    info "htpasswd not found locally; using nginx Docker image..."
    docker run --rm -it \
        -v "$(realpath "$(dirname "$HTPASSWD_FILE")"):/auth" \
        nginx:1.27-alpine \
        htpasswd -B -C 12 /auth/htpasswd.txt "$USERNAME"
fi

success "User '$USERNAME' saved to $HTPASSWD_FILE"
info "Reload nginx (no downtime): docker compose exec nginx nginx -s reload"
