waht is #!/usr/bin/env bash
set -euo pipefail

# One-shot bootstrap for trading-poc paper deployment on Ubuntu EC2.
# Usage:
#   ./deploy/systemd/bootstrap_paper_ec2.sh <repo_url> [project_dir]
# Example:
#   ./deploy/systemd/bootstrap_paper_ec2.sh git@github.com:org/trading-poc.git /opt/trading-poc

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <repo_url> [project_dir]"
  exit 1
fi

REPO_URL="$1"
PROJECT_DIR="${2:-/opt/trading-poc}"
SERVICE_NAME="trading-poc"
SERVICE_FILE="deploy/systemd/trading-poc.service"

if [[ "$(id -u)" -eq 0 ]]; then
  echo "Run this script as a non-root user with sudo access (for example: ubuntu)."
  exit 1
fi

if ! command -v sudo >/dev/null 2>&1; then
  echo "sudo is required but not found."
  exit 1
fi

echo "[1/10] Installing system packages..."
sudo apt-get update
sudo apt-get install -y git python3 python3-venv python3-pip

if [[ ! -d "$PROJECT_DIR/.git" ]]; then
  echo "[2/10] Cloning project into $PROJECT_DIR ..."
  sudo mkdir -p "$(dirname "$PROJECT_DIR")"
  sudo git clone "$REPO_URL" "$PROJECT_DIR"
fi

echo "[3/10] Setting ownership to $USER ..."
sudo chown -R "$USER":"$USER" "$PROJECT_DIR"

cd "$PROJECT_DIR"

echo "[4/10] Creating Python virtual environment ..."
python3 -m venv .venv

# shellcheck disable=SC1091
source .venv/bin/activate

echo "[5/10] Installing Python dependencies ..."
pip install --upgrade pip
pip install -r requirements.txt

echo "[6/10] Preparing .env ..."
if [[ ! -f .env ]]; then
  cp .env.example .env
fi

sed -i 's/^MODE=.*/MODE=paper/' .env
sed -i 's/^BROKER=.*/BROKER=paper/' .env
sed -i 's/^PAPER_TRADE=.*/PAPER_TRADE=true/' .env
sed -i 's/^OPENROUTER_ENABLED=.*/OPENROUTER_ENABLED=false/' .env
sed -i 's/^AUTO_RUN_ENABLED=.*/AUTO_RUN_ENABLED=true/' .env

echo "[7/10] Installing systemd service ..."
if [[ ! -f "$SERVICE_FILE" ]]; then
  echo "Missing $SERVICE_FILE in repo."
  exit 1
fi

sudo cp "$SERVICE_FILE" "/etc/systemd/system/${SERVICE_NAME}.service"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"


echo "[8/10] Restarting service ..."
sudo systemctl restart "$SERVICE_NAME"

echo "[9/10] Verifying service state ..."
sudo systemctl status "$SERVICE_NAME" --no-pager

echo "[10/10] Running local health checks ..."
curl -sS http://127.0.0.1:8000/health || true
curl -sS http://127.0.0.1:8000/ops/paper-ready || true
curl -sS http://127.0.0.1:8000/runner/status || true
curl -sS http://127.0.0.1:8000/report/today || true

echo "Bootstrap complete. Follow logs with:"
echo "  sudo journalctl -u ${SERVICE_NAME} -f"
