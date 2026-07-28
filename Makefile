.PHONY: up down logs api worker fe migrate revision test lint nightly

up:            ## Start full stack (db, redis, api, worker)
	docker compose up -d --build

down:          ## Stop everything
	docker compose down

logs:          ## Tail all service logs
	docker compose logs -f

api:           ## Run API locally (outside docker)
	cd backend && EDGELAB_RESEARCH_ROOT=$$PWD/research_data EDGELAB_DATA_ROOT=$$PWD/data/store EDGELAB_OPS_ROOT=$$PWD/ops_data uvicorn app.main:app --reload --port 8000

seed:          ## Seed synthetic data + demo experiments
	cd backend && python scripts/seed_research.py

nightly:       ## Run the continuous-research nightly batch once, locally
	cd backend && EDGELAB_RESEARCH_ROOT=$$PWD/research_data EDGELAB_DATA_ROOT=$$PWD/data/store EDGELAB_OPS_ROOT=$$PWD/ops_data python scripts/run_nightly.py

worker:        ## Run Celery worker locally
	cd backend && celery -A app.workers.celery_app worker --loglevel=info

fe:            ## Run Next.js dev server
	cd frontend && npm run dev

migrate:       ## Apply DB migrations
	cd backend && alembic upgrade head

revision:      ## Autogenerate a migration: make revision m="add trades table"
	cd backend && alembic revision --autogenerate -m "$(m)"

test:          ## Run backend tests
	cd backend && pytest -q

lint:          ## Lint + typecheck backend
	cd backend && ruff check . && mypy app engine
