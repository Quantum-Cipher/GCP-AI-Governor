VENV=.venv
PYTHON=$(VENV)/bin/python3
PIP=$(VENV)/bin/pip

MAIN=daemon/main.py
SIMULATOR=daemon/simulator/simulate_event.py
SMOKE_SCRIPT=scripts/smoke_test.sh

.PHONY: help dev install run simulate smoke clean test

help:
	@echo "Available commands:"
	@echo "  make dev       - create venv and install dependencies"
	@echo "  make install   - install dependencies"
	@echo "  make run       - start governance agent"
	@echo "  make simulate  - run event simulator"
	@echo "  make smoke     - run health check + simulator"
	@echo "  make test      - run smoke test"
	@echo "  make clean     - remove caches and logs"

dev:
	python3 -m venv $(VENV)
	$(PYTHON) -m pip install --upgrade pip
	$(PIP) install -r requirements.txt

install:
	$(PYTHON) -m pip install --upgrade pip
	$(PIP) install -r requirements.txt

run:
	$(PYTHON) $(MAIN)

simulate:
	$(PYTHON) $(SIMULATOR)

smoke:
	bash $(SMOKE_SCRIPT)

test:
	bash $(SMOKE_SCRIPT)

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -f smoke_test_server.log
