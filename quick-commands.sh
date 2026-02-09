#!/bin/bash

# Quick commands for Zentrya Backend

case $1 in
  "start")
    echo "🚀 Starting Zentrya services..."
    docker-compose up -d
    ;;
  "stop")
    echo "🛑 Stopping Zentrya services..."
    docker-compose down
    ;;
  "restart")
    echo "🔄 Restarting Zentrya services..."
    docker-compose restart
    ;;
  "logs")
    echo "📝 Showing API logs..."
    docker-compose logs -f api
    ;;
  "migrate")
    echo "🗄️ Running database migrations..."
    docker-compose exec api alembic upgrade head
    ;;
  "create-admin")
    echo "👤 Creating admin user..."
    docker-compose exec api python -m app.initial_data
    ;;
  "shell")
    echo "🐚 Opening API container shell..."
    docker-compose exec api bash
    ;;
  "db-shell")
    echo "🗄️ Opening database shell..."
    docker-compose exec postgres psql -U zentrya_user -d zentrya_db
    ;;
  "redis-shell")
    echo "📦 Opening Redis shell..."
    docker-compose exec redis redis-cli
    ;;
  "test")
    echo "🧪 Running tests..."
    docker-compose exec api pytest
    ;;
  "reset")
    echo "⚠️  Resetting all data (THIS WILL DELETE EVERYTHING)..."
    read -p "Are you sure? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
      docker-compose down -v
      docker-compose up -d
      sleep 10
      docker-compose exec api alembic upgrade head
      docker-compose exec api python -m app.initial_data
      echo "✅ Reset complete!"
    fi
    ;;
  *)
    echo "Zentrya Backend Quick Commands"
    echo ""
    echo "Usage: ./quick-commands.sh [command]"
    echo ""
    echo "Commands:"
    echo "  start        - Start all services"
    echo "  stop         - Stop all services"
    echo "  restart      - Restart all services"
    echo "  logs         - Show API logs"
    echo "  migrate      - Run database migrations"
    echo "  create-admin - Create admin user"
    echo "  shell        - Open API container shell"
    echo "  db-shell     - Open database shell"
    echo "  redis-shell  - Open Redis shell"
    echo "  test         - Run tests"
    echo "  reset        - Reset all data (DANGEROUS)"
    echo ""
    echo "Examples:"
    echo "  ./quick-commands.sh start"
    echo "  ./quick-commands.sh logs"
    echo "  ./quick-commands.sh migrate"
    ;;
esac
