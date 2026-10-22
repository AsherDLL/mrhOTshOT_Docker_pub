# mrhOTshOT Docker profile. Run from the repo root.
#
# Everything runs in containers. The host needs Docker, the Compose plugin and
# python3. Start with `make install`, or ./scripts/install.sh.

LAB     := docker compose -f docker/docker-compose.yml
CONSOLE := docker compose -f docker/console.yml
SENSOR  := docker compose -f docker/sensor.yml
PY      := python3

DETECT_DIR := final_things/iec104_water_tank/demo/detections

.PHONY: help install preflight lab-up lab-stop lab-down lab-ps hmi-seed \
        console-up console-down console-logs sensor-up sensor-down sensor-logs \
        test test-int lint clean

help:
	@echo "mrhOTshOT Docker profile:"
	@echo "  install       preflight, build and start everything"
	@echo "  preflight     check this host without changing anything"
	@echo "  lab-up        build and start the OT target lab"
	@echo "  lab-stop      stop the lab, keep volumes and the seeded HMI"
	@echo "  lab-down      stop the lab and remove its volumes"
	@echo "  lab-ps        container status"
	@echo "  hmi-seed      load the operator view into FUXA (http://localhost:1881/home)"
	@echo "  console-up    start the dashboard (http://127.0.0.1:8888)"
	@echo "  console-down  stop the dashboard"
	@echo "  console-logs  follow dashboard logs"
	@echo "  sensor-up     start the passive Suricata IDS (optional)"
	@echo "  sensor-down   stop the sensor"
	@echo "  sensor-logs   follow IDS alerts"
	@echo "  test          unit tests (integration tests self-skip)"
	@echo "  test-int      full suite including docker integration tests"
	@echo "  lint          ruff check"
	@echo "  clean         stop everything and remove the built images"

install:
	./scripts/install.sh

preflight:
	@sh scripts/preflight.sh

lab-up:
	$(LAB) up -d --build
	@$(LAB) ps
	@$(MAKE) --no-print-directory hmi-seed

# Stops containers without touching volumes. Use this rather than lab-down if
# you want the seeded FUXA view to still be there next time.
lab-stop:
	$(LAB) stop
	-$(CONSOLE) stop

lab-down:
	$(LAB) down -v

lab-ps:
	$(LAB) ps

# Non-destructive: skips if the view is already loaded. Needs fuxa answering.
hmi-seed:
	@$(PY) scripts/seed_fuxa_hmi.py --wait || \
	  echo "[!] HMI seed skipped; run 'make hmi-seed' once FUXA (http://localhost:1881) is up"

console-up:
	-docker network create otlab 2>/dev/null
	$(CONSOLE) up -d --build
	@echo "Dashboard: http://127.0.0.1:8888"

console-down:
	$(CONSOLE) down

console-logs:
	$(CONSOLE) logs -f

# Passive IDS on the lab's docker bridges. Run `make lab-up` first so the
# bridges exist. Swap the image in docker/sensor.yml for your own engine.
sensor-up:
	@mkdir -p $(DETECT_DIR) && chmod 777 $(DETECT_DIR) 2>/dev/null || true
	SENSOR_IFACES="$$(sh docker/sensor_ifaces.sh)" $(SENSOR) up -d --build
	@echo "Sensor up. Alerts: 'make sensor-logs' or the dashboard Detections tab."

sensor-down:
	$(SENSOR) down

sensor-logs:
	@echo "Live OT IDS alerts (Ctrl-C to stop). Launch an attack to see detections..."
	@touch $(DETECT_DIR)/fast.log 2>/dev/null || true
	@tail -n 50 -f $(DETECT_DIR)/fast.log

# Tests need the dev deps on the host:
#   pip install -r requirements.txt -r requirements-dev.txt
test:
	$(PY) -m pytest -q

test-int:
	$(PY) -m pytest -q -o addopts=""

lint:
	$(PY) -m ruff check .

clean:
	-$(CONSOLE) down
	-$(SENSOR) down
	-$(LAB) down -v
	-docker image rm mrhotshot/target mrhotshot/console mrhotshot/fuxa mrhotshot/caldera mrhotshot/sensor 2>/dev/null
	@echo "[OK] lab stopped and built images removed"
