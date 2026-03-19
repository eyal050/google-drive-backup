#!/usr/bin/env bash
# install.sh — gdrive-backup installer and setup launcher
# Usage: curl -sSL https://raw.githubusercontent.com/eyal050/google-drive-backup/main/install.sh | bash
set -euo pipefail

REPO="eyal050/google-drive-backup"
BRANCH="main"
SETUP_URL="https://raw.githubusercontent.com/${REPO}/${BRANCH}/scripts/setup.py"

# ── Colours ──────────────────────────────────────────────────────────────────
BOLD='\033[1m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; RESET='\033[0m'
info()    { echo -e "${BOLD}$*${RESET}"; }
success() { echo -e "${GREEN}✓ $*${RESET}"; }
warn()    { echo -e "${YELLOW}! $*${RESET}"; }
err()     { echo -e "${RED}✗ $*${RESET}" >&2; }

# ── Python check ─────────────────────────────────────────────────────────────
check_python() {
    if ! command -v python3 &>/dev/null; then
        err "Python 3.10+ is required but was not found on your PATH."
        if [[ "${OSTYPE:-}" == "darwin"* ]]; then
            err "  Install with: brew install python"
        elif command -v apt-get &>/dev/null; then
            err "  Install with: sudo apt-get install python3"
        elif command -v winget &>/dev/null; then
            err "  Install with: winget install Python.Python.3"
        else
            err "  Download from: https://www.python.org/downloads/"
        fi
        exit 1
    fi

    local ok
    ok=$(python3 -c "
import sys
cur = sys.version_info[:2]
print('ok' if cur >= (3, 10) else 'old')
")
    if [[ "$ok" != "ok" ]]; then
        err "Python 3.10+ is required. Found: $(python3 --version 2>&1)"
        exit 1
    fi
}

# ── Version comparison (stdlib, no packaging dependency) ─────────────────────
version_gt() {
    # Returns 0 (true) if $1 > $2 as dotted-integer version strings
    python3 - "$1" "$2" <<'EOF'
import sys
a = tuple(int(x) for x in sys.argv[1].split(".")[:3])
b = tuple(int(x) for x in sys.argv[2].split(".")[:3])
sys.exit(0 if a > b else 1)
EOF
}

# ── PyPI latest version ───────────────────────────────────────────────────────
get_pypi_version() {
    local pypi_url="https://pypi.org/pypi/gdrive-backup/json"
    local ver=""

    # Try curl first
    if command -v curl &>/dev/null; then
        ver=$(curl -sSf "$pypi_url" 2>/dev/null \
            | python3 -c "
import sys, json
try:
    print(json.load(sys.stdin)['info']['version'])
except Exception:
    pass
" 2>/dev/null || true)
    fi

    # Fallback to urllib
    if [[ -z "$ver" ]]; then
        ver=$(python3 -c "
import urllib.request, json
try:
    with urllib.request.urlopen('${pypi_url}', timeout=5) as r:
        print(json.load(r)['info']['version'])
except Exception:
    pass
" 2>/dev/null || true)
    fi

    echo "$ver"
}

# ── Download helper ───────────────────────────────────────────────────────────
download_file() {
    local url="$1" dest="$2"
    if command -v curl &>/dev/null; then
        curl -sSL "$url" -o "$dest"
    else
        python3 -c "
import urllib.request
urllib.request.urlretrieve('$url', '$dest')
"
    fi
}

# ── Main ──────────────────────────────────────────────────────────────────────
echo ""
info "gdrive-backup installer"
echo "──────────────────────────────────────"

check_python

# Determine installed version
installed_ver=""
if pip show gdrive-backup &>/dev/null 2>&1; then
    installed_ver=$(pip show gdrive-backup 2>/dev/null | grep "^Version:" | awk '{print $2}')
fi

# Get latest version from PyPI
info "Checking latest version on PyPI..."
latest_ver=$(get_pypi_version)

if [[ -z "$latest_ver" ]]; then
    warn "Could not reach PyPI — skipping version check."
fi

if [[ -z "$installed_ver" ]]; then
    # ── Not installed ───────────────────────────────────────────────────────
    info "Installing gdrive-backup..."
    if ! pip install gdrive-backup; then
        err "Installation failed."
        err "Try: pip install --user gdrive-backup"
        exit 1
    fi
    success "Installed gdrive-backup."

elif [[ -n "$latest_ver" ]] && version_gt "$latest_ver" "$installed_ver"; then
    # ── Outdated ────────────────────────────────────────────────────────────
    echo ""
    read -r -p "Update gdrive-backup from v${installed_ver} to v${latest_ver}? [Y/n] " response
    if [[ -z "$response" || "$response" =~ ^[Yy] ]]; then
        info "Updating..."
        if ! pip install --upgrade gdrive-backup; then
            err "Update failed."
            err "Try: pip install --user --upgrade gdrive-backup"
            exit 1
        fi
        success "Updated to v${latest_ver}."
    else
        warn "Skipping update. Continuing with v${installed_ver}."
    fi

else
    # ── Up to date ──────────────────────────────────────────────────────────
    success "Already installed (v${installed_ver}, up to date). Proceeding to configuration..."
fi

echo ""

# ── Download and run setup wizard ────────────────────────────────────────────
SETUP_TMP=$(mktemp /tmp/gdrive-setup.XXXXXX.py)
trap 'rm -f "$SETUP_TMP"' EXIT

info "Downloading setup wizard..."
download_file "$SETUP_URL" "$SETUP_TMP"

python3 "$SETUP_TMP"
