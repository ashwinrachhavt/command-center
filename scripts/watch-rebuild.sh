#!/bin/bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

rebuild_service() {
    local service="$1"
    echo "🔨 Rebuilding $service..."

    echo "  → Stopping old containers..."
    docker compose stop "$service" 2>/dev/null || true

    echo "  → Removing old containers..."
    docker compose rm -f "$service" 2>/dev/null || true

    echo "  → Building new image..."
    docker compose build "$service"

    echo "  → Starting service..."
    docker compose up -d "$service"

    echo "✅ $service rebuilt successfully"
}

show_usage() {
    cat << EOF
Usage: $(basename "$0") [OPTIONS] [SERVICE...]

Rebuild Docker services with changes and remove old containers.

OPTIONS:
    --all           Rebuild all services
    --api           Rebuild API and related services (worker, integration-worker, beat)
    --web           Rebuild web service
    --worker        Rebuild execution-worker service
    --help          Show this help message

SERVICES:
    Specific service names from compose.yaml (api, web, worker, etc.)

EXAMPLES:
    $(basename "$0") --all
    $(basename "$0") --api
    $(basename "$0") --web
    $(basename "$0") api web
EOF
}

if [ $# -eq 0 ]; then
    show_usage
    exit 1
fi

case "$1" in
    --help|-h)
        show_usage
        exit 0
        ;;
    --all)
        echo "🔄 Rebuilding all services..."
        docker compose down
        docker compose up -d --build --wait
        echo "✅ All services rebuilt"
        ;;
    --api)
        rebuild_service "api"
        rebuild_service "worker"
        rebuild_service "integration-worker"
        rebuild_service "beat"
        ;;
    --web)
        rebuild_service "web"
        ;;
    --worker)
        rebuild_service "execution-worker"
        ;;
    *)
        for service in "$@"; do
            rebuild_service "$service"
        done
        ;;
esac
