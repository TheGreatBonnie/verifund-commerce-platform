.PHONY: setup dev dev-scripted seed seed-demo reset test lint e2e demo down \
	verifund-smoke verifund-e2e verifund-demo verifund-preflight \
	verifund-sandbox-smoke

setup:
	uv lock
	uv sync --all-packages
	cd apps/console && pnpm install
	cp -n .env.example .env || true

dev:
	uv run python scripts/dev.py

dev-scripted:
	uv run python scripts/dev.py --scripted

seed:
	uv run python scripts/seed.py

seed-demo:
	MARKETMESH_SEED_DEMO=1 uv run python scripts/seed.py

reset:
	rm -f data/*.db data/*.db-wal data/*.db-shm
	rm -rf data/evidence

test:
	uv run pytest

lint:
	uv run ruff check .
	cd apps/console && pnpm run typecheck

e2e:
	uv run python scripts/e2e.py

demo:
	uv run python scripts/run_demo.py


verifund-smoke:
	uv run python scripts/verifund_smoke.py

verifund-e2e:
	uv run python scripts/verifund_e2e.py

verifund-demo:
	uv run python scripts/run_demo.py --verifund fake

verifund-preflight:
	uv run python scripts/verifund_sandbox_preflight.py

verifund-sandbox-smoke:
	uv run python scripts/verifund_sandbox_smoke.py


down:
	uv run python scripts/dev.py stop
