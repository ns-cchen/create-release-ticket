# Create Release Ticket - Makefile
# Development commands for CLI and Web UI

.PHONY: help install dev dev-backend dev-frontend build clean test lint cli test-e2e test-e2e-ui

# Default target
help:
	@echo "Create Release Ticket - Development Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make install        Install all dependencies (CLI + Web UI)"
	@echo ""
	@echo "Development:"
	@echo "  make dev            Start both backend and frontend"
	@echo "  make dev-backend    Start backend only (port 5004)"
	@echo "  make dev-frontend   Start frontend only (port 3005)"
	@echo ""
	@echo "CLI:"
	@echo "  make cli            Run CLI tool (use ARGS for options)"
	@echo "                      Example: make cli ARGS='run --dry-run -b ... -r ...'"
	@echo ""
	@echo "Build:"
	@echo "  make build          Build frontend for production"
	@echo ""
	@echo "Testing:"
	@echo "  make test           Run all tests"
	@echo "  make test-e2e       Run Playwright E2E tests"
	@echo "  make test-e2e-ui    Run Playwright E2E tests with UI"
	@echo "  make lint           Run linters"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean          Remove build artifacts"

# Install all dependencies
install:
	@echo "Installing CLI dependencies..."
	poetry install
	@echo ""
	@echo "Installing frontend dependencies..."
	cd frontend && npm install
	@echo ""
	@echo "Done! Run 'make dev' to start development servers."

# Development servers
dev:
	@echo "Starting development servers..."
	@echo "Backend: http://localhost:5004"
	@echo "Frontend: http://localhost:3004"
	@echo ""
	@$(MAKE) -j2 dev-backend dev-frontend

dev-backend:
	BACKEND_PORT=5004 poetry run uvicorn backend.main:app --reload --port 5004

dev-frontend:
	cd frontend && VITE_API_URL=http://localhost:5004 npm run dev

# CLI
cli:
	poetry run create-release-ticket $(ARGS)

# Build
build:
	cd frontend && npm run build

# Testing
test:
	poetry run pytest
	cd frontend && npm run test

test-backend:
	poetry run pytest

test-frontend:
	cd frontend && npm run test

# E2E Testing (Playwright)
test-e2e:
	cd frontend && npm run test:e2e

test-e2e-ui:
	cd frontend && npm run test:e2e:ui

# Linting
lint:
	poetry run ruff check src/
	cd frontend && npm run lint

# Cleanup
clean:
	rm -rf frontend/dist
	rm -rf frontend/node_modules/.vite
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
