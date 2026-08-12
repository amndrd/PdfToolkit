# Recto — development shortcuts.
# Everything here also works as a plain command; this is convenience, not magic.

PYTHON ?= python
VENV   ?= .venv
BIN    := $(VENV)/bin

.DEFAULT_GOAL := help
.PHONY: help install test cov lint format types check serve build clean

help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install:  ## Create the virtualenv and install with dev extras
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e ".[dev]"

test:  ## Run the test suite
	$(BIN)/pytest

cov:  ## Run the tests with a coverage report
	$(BIN)/pytest --cov=recto --cov-report=term-missing --cov-report=html
	@echo "HTML report: htmlcov/index.html"

lint:  ## Lint with ruff
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

format:  ## Format with ruff
	$(BIN)/ruff format .
	$(BIN)/ruff check --fix .

types:  ## Type-check with mypy
	$(BIN)/mypy

check: lint types test  ## Everything CI runs

serve:  ## Start the web interface
	$(BIN)/recto serve

build:  ## Build the sdist and wheel
	$(BIN)/pip install --quiet build twine
	$(BIN)/python -m build
	$(BIN)/twine check --strict dist/*

clean:  ## Remove build and cache artefacts
	rm -rf build dist *.egg-info src/*.egg-info htmlcov .coverage coverage.xml
	rm -rf .pytest_cache .ruff_cache .mypy_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
