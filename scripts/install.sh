#!/usr/bin/env sh
# One-shot setup for the mrhOTshOT Docker profile.
#
#   ./scripts/install.sh              build and start everything
#   ./scripts/install.sh --no-build   start without rebuilding images
#   ./scripts/install.sh --lab-only   skip the dashboard
#
# Safe to re-run. It does not remove volumes, so a seeded HMI survives.
set -eu

REPO=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$REPO"

LAB="docker compose -f docker/docker-compose.yml"
CONSOLE="docker compose -f docker/console.yml"
BUILD="--build"
LAB_ONLY=0

for arg in "$@"; do
    case "$arg" in
        --no-build) BUILD="" ;;
        --lab-only) LAB_ONLY=1 ;;
        -h|--help)  sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) printf '[!!]  unknown option: %s\n' "$arg"; exit 2 ;;
    esac
done

step() { printf '\n==> %s\n' "$1"; }
die()  { printf '\n[!!]  %s\n' "$1"; exit 1; }

step "Checking the host"
sh scripts/preflight.sh || die "preflight found a blocker. Fix the items above and run this again."

step "Creating the otlab network"
# The lab and the dashboard are separate compose projects that share this
# network, so it has to exist before either one starts.
if docker network inspect otlab >/dev/null 2>&1; then
    echo "[OK]  otlab already exists"
else
    docker network create otlab >/dev/null && echo "[OK]  otlab created"
fi

step "Building and starting the target lab"
echo "The first build pulls base images and clones the MITRE OT plugins."
echo "Expect it to take several minutes and need network access."
# shellcheck disable=SC2086
$LAB up -d $BUILD || die "the lab failed to build or start.
      If the Caldera stage failed, it clones github.com/mitre/{modbus,dnp3,bacnet,iec61850}
      at build time and needs network. Retry, or comment out the caldera and
      caldera-agent services in docker/docker-compose.yml to bring up the rest."

step "Lab status"
$LAB ps

step "Seeding the operator HMI"
# Non-destructive and safe to re-run. Needs the fuxa container answering first.
python3 scripts/seed_fuxa_hmi.py --wait ||
    echo "[!]   HMI seed did not complete. Run 'make hmi-seed' once http://localhost:1881 answers."

if [ "$LAB_ONLY" -eq 0 ]; then
    step "Starting the dashboard"
    # shellcheck disable=SC2086
    $CONSOLE up -d $BUILD || die "the dashboard failed to start. Check 'make console-logs'."
fi

cat <<'DONE'

==> Ready

  Dashboard         http://127.0.0.1:8888
  Operator HMI      http://localhost:1881/home
  Caldera           http://localhost:8889   (login root:root, lab defaults)

  make lab-ps         container status
  make console-logs   dashboard logs
  make lab-stop       stop everything, keep the seeded HMI
  make lab-down       stop everything and remove volumes

Pick an attack in the dashboard, press Launch, then open Visualize to watch the
process react. Restore puts the plant back.
DONE
