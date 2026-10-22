.PHONY: setup dev dev-scripted seed reset test lint e2e demo down

setup:
	uv lock
	uv sync --all-packages
	cd apps/console && npm install
	cp -n .env.example .env || true

dev:
	uv run python scripts/dev.py

dev-scripted:
	uv run python scripts/dev.py --scripted

seed:
	uv run python scripts/seed.py

reset:
	rm -f data/*.db data/*.db-wal data/*.db-shm

test:
	uv run pytest

lint:
	uv run ruff check .
	cd apps/console && npm run typecheck

e2e:
	uv run python scripts/e2e.py

demo:
	uv run python scripts/run_demo.py

down:
	uv run python scripts/dev.py stop
