#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# scripts/publish.sh
# Builds and publishes pytest-api-core to an Artifactory PyPI repository.
#
# Required environment variables:
#   PYPI_SERVER_URL   e.g. https://pypi.yourdomain.com
#   PYPI_USERNAME     pypiserver username
#   PYPI_PASSWORD     pypiserver password
#
# Optional:
#   SKIP_TESTS=1        Skip running the test suite before publishing
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

# ---- Colour helpers --------------------------------------------------------
info()    { echo -e "\033[0;34m[INFO]\033[0m  $*"; }
success() { echo -e "\033[0;32m[OK]\033[0m    $*"; }
error()   { echo -e "\033[0;31m[ERROR]\033[0m $*" >&2; exit 1; }

# ---- Validate env vars -----------------------------------------------------
: "${PYPI_SERVER_URL:?PYPI_SERVER_URL must be set (e.g. https://pypi.yourdomain.com)}"
: "${PYPI_USERNAME:?PYPI_USERNAME must be set}"
: "${PYPI_PASSWORD:?PYPI_PASSWORD must be set}"

# ---- Change to project root ------------------------------------------------
cd "$ROOT_DIR"

# ---- Optionally run tests --------------------------------------------------
if [[ "${SKIP_TESTS:-0}" != "1" ]]; then
    info "Running test suite..."
    python -m pytest tests/ -x -q --no-header \
        --ignore=tests/test_sample_api.py  # skip integration tests in CI
    success "Tests passed"
fi

# ---- Clean previous build artefacts ----------------------------------------
info "Cleaning dist/ and build/ directories..."
rm -rf dist/ build/ src/*.egg-info

# ---- Build source dist + wheel ---------------------------------------------
info "Building package..."
python -m build --sdist --wheel
success "Build complete: $(ls dist/)"

# ---- Upload to private pypiserver ------------------------------------------
info "Uploading to pypiserver: $PYPI_SERVER_URL"
python -m twine upload \
    --repository-url "$PYPI_SERVER_URL" \
    --username "$PYPI_USERNAME" \
    --password "$PYPI_PASSWORD" \
    --non-interactive \
    --verbose \
    dist/*

success "Package published successfully!"
echo ""
echo "Install via:"
echo "  pip install pytest-api-core \\"
echo "    --index-url https://\$PYPI_USERNAME:\$PYPI_PASSWORD@${PYPI_SERVER_URL#https://}/simple/"
