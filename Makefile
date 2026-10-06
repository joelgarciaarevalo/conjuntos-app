# IRIS 3.1 · tareas locales para macOS/Linux
SHELL := /bin/bash

.PHONY: help install dev-api dev-web test build clean
help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-14s %s\n", $$1, $$2}'

install: ## Instala dependencias locales de API e interfaz
	python3 -m venv backend/.venv
	backend/.venv/bin/pip install -r backend/requirements.txt
	cd frontend && npm ci

dev-api: ## Inicia API local en http://127.0.0.1:8000
	cd backend && APP_ENV=development .venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

dev-web: ## Inicia Angular en http://localhost:4200
	cd frontend && npm start

test: ## Ejecuta pruebas backend
	cd backend && .venv/bin/python -m pytest -q

build: ## Compila frontend
	cd frontend && npm run build

clean: ## Elimina artefactos de compilación y cachés
	rm -rf frontend/dist frontend/.angular backend/.pytest_cache backend/app/__pycache__ backend/app/routers/__pycache__ backend/tests/__pycache__
