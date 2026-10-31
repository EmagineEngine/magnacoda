.PHONY: install install-dev lint test test-unit test-integration build check check-wheel

install:
	pip install -e .

install-dev:
	pip install -e ".[dev]"
	playwright install chromium

lint:
	ruff check magnacoda magnacoda_addons tests scripts
	ruff format --check magnacoda magnacoda_addons tests scripts
	mypy

# In parallel (pytest-xdist): past 3 workers the unit tests get no faster; the browser tests do up to 4.
# At low priority (nice), so the desktop stays responsive while they run.
test-unit:
	nice -n 10 pytest -n 3 -m "not integration and not live_api"

test-integration:
	nice -n 10 pytest -n 4 -m "integration and not live_api"

test: test-unit test-integration

build:
	python -m build

check: build
	twine check dist/*

# Build the wheel, install it into a fresh environment and try it (scripts/check_wheel.py).
check-wheel:
	python scripts/check_wheel.py

# Write the contents lists of the README and the manual from their headings (scripts/readme_toc.py).
toc:
	python scripts/readme_toc.py
