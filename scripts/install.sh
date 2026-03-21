#!/usr/bin/env bash
set -euo pipefail

echo "=== Majic Movie Selector - Install ==="
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Detect if running from cloned repo or fresh install
if [[ -f "$(dirname "${BASH_SOURCE[0]}")/../app/main.py" ]]; then
    ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    FRESH_INSTALL=false
else
    ROOT_DIR="$HOME/majic-movies"
    FRESH_INSTALL=true
fi

# Install system dependencies if needed
install_system_deps() {
    echo -e "${YELLOW}Checking system dependencies...${NC}"
    if ! command -v python3 &> /dev/null; then
        if command -v apt-get &> /dev/null; then
            sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip git
        elif command -v yum &> /dev/null; then
            sudo yum install -y python3 python3-pip git
        elif command -v dnf &> /dev/null; then
            sudo dnf install -y python3 python3-pip git
        elif command -v brew &> /dev/null; then
            brew install python3 git
        fi
    fi
}

# Clone repo if fresh install
if [[ "$FRESH_INSTALL" == true ]]; then
    install_system_deps
    if [[ -d "$ROOT_DIR" ]]; then
        echo -e "${YELLOW}Updating existing installation...${NC}"
        cd "$ROOT_DIR"
        git pull
    else
        echo -e "${YELLOW}Cloning repository...${NC}"
        git clone https://github.com/W00t3k/Awesome-Usenet.git "$ROOT_DIR"
    fi
fi

cd "$ROOT_DIR"
PYTHON="${PYTHON:-python3}"
VENV_DIR="$ROOT_DIR/.venv"

# Check Python version
echo "Checking Python..."
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "ERROR: $PYTHON not found. Install Python 3.11+ and retry."
    exit 1
fi

PY_VERSION="$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_MAJOR="$("$PYTHON" -c 'import sys; print(sys.version_info.major)')"
PY_MINOR="$("$PYTHON" -c 'import sys; print(sys.version_info.minor)')"

if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 11 ]]; }; then
    echo "ERROR: Python 3.11+ required (found $PY_VERSION)."
    exit 1
fi
echo -e "  Found Python $PY_VERSION ${GREEN}✓${NC}"

# Create virtual environment
if [[ -d "$VENV_DIR" ]]; then
    echo "Virtual environment exists ✓"
else
    echo "Creating virtual environment..."
    "$PYTHON" -m venv "$VENV_DIR"
    echo -e "  Created $VENV_DIR ${GREEN}✓${NC}"
fi

PIP="$VENV_DIR/bin/pip"

# Install dependencies
echo "Installing dependencies..."
"$PIP" install --upgrade pip --quiet
"$PIP" install -r "$ROOT_DIR/requirements.txt" --quiet
echo -e "  Dependencies installed ${GREEN}✓${NC}"

# Create .env if missing
if [[ ! -f "$ROOT_DIR/.env" ]]; then
    echo "Creating .env file..."
    cat > "$ROOT_DIR/.env" << 'ENVEOF'
# === Majic Movie Selector Configuration ===

# AI Provider (get free key at https://console.groq.com)
GROQ_API_KEY=
GROQ_MODEL=llama-3.3-70b-versatile

# Movie data & posters (https://www.themoviedb.org/settings/api)
TMDB_API_KEY=

# Usenet indexers (optional)
NZBGEEK_API_KEY=
DRUNKENSLUG_API_KEY=

# Local services (use Tailscale IPs if accessing remotely)
PLEX_BASE_URL=http://localhost:32400
PLEX_TOKEN=
RADARR_BASE_URL=http://localhost:7878
RADARR_API_KEY=

# Optional: Local Ollama instead of Groq
# OLLAMA_BASE_URL=http://localhost:11434
# OLLAMA_MODEL=llama3.2:3b
ENVEOF
    echo -e "  Created .env ${GREEN}✓${NC}"
fi

# Create systemd service (Linux only)
if [[ -d /etc/systemd/system ]] && command -v systemctl &> /dev/null; then
    echo "Creating systemd service..."
    sudo tee /etc/systemd/system/majic-movies.service > /dev/null << EOF
[Unit]
Description=Majic Movie Selector
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$ROOT_DIR
EnvironmentFile=$ROOT_DIR/.env
ExecStart=$VENV_DIR/bin/uvicorn app.main:app --host 0.0.0.0 --port 8443
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload
    sudo systemctl enable majic-movies
    echo -e "  Systemd service created ${GREEN}✓${NC}"
    HAS_SYSTEMD=true
else
    HAS_SYSTEMD=false
fi

# Done
echo ""
echo -e "${GREEN}══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Installation complete!${NC}"
echo -e "${GREEN}══════════════════════════════════════════════${NC}"
echo ""
echo "Next steps:"
echo "  1. Edit API keys:  nano $ROOT_DIR/.env"
echo ""
if [[ "$HAS_SYSTEMD" == true ]]; then
    echo "  2. Start service:  sudo systemctl start majic-movies"
    echo "  3. View logs:      sudo journalctl -u majic-movies -f"
else
    echo "  2. Start server:   cd $ROOT_DIR && source .venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8443"
fi
echo ""
echo "  Open in browser:   http://YOUR_IP:8443"
echo ""
echo "Optional - Connect to home Plex/Radarr via Tailscale:"
echo "  curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up"
