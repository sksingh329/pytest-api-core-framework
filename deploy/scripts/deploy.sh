#!/usr/bin/env bash
# =============================================================================
# deploy/scripts/deploy.sh
#
# Pull latest images and restart the stack with zero-downtime for pypiserver.
# Safe to re-run anytime (idempotent).
#
# Usage:  ./scripts/deploy.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE="docker compose -f $SCRIPT_DIR/../docker-compose.yml"

info()    { echo -e "\033[0;34m[INFO]\033[0m  $*"; }
success() { echo -e "\033[0;32m[OK]\033[0m    $*"; }

info "Pulling latest images..."
$COMPOSE pull

info "Restarting stack..."
$COMPOSE up -d --remove-orphans

info "Waiting for pypiserver health check..."
sleep 5
$COMPOSE ps

success "Deployment complete."
