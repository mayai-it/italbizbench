.PHONY: dev test lint types check clean

dev:
	pip install -e ".[dev]"

test:
	pytest -q

lint:
	ruff check italbizbench/ tests/ examples/

types:
	mypy --strict italbizbench/

check: lint types test

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
