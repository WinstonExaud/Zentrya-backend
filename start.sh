#!/bin/bash

# Zentrya Platform Startup Script
# Automatically syncs time and starts containers

set -e

echo "🚀 Starting Zentrya Platform..."
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running as root (needed for time sync)
if [ "$EUID" -ne 0 ] && command -v sudo &> /dev/null; then 
    SUDO='sudo'
else
    SUDO=''
fi

# Step 1: Sync system time
echo "⏰ Step 1: Syncing system time..."
if command -v ntpdate &> /dev/null; then
    $SUDO ntpdate -s time.nist.gov 2>/dev/null || echo "ntpdate failed, trying timedatectl..."
fi

if command -v timedatectl &> /dev/null; then
    $SUDO timedatectl set-ntp true 2>/dev/null || true
    echo -e "${GREEN}✓${NC} System time synced"
else
    echo -e "${YELLOW}⚠${NC} Could not sync time automatically. Please run: sudo ntpdate -s time.nist.gov"
fi

# Show current time
echo "Current system time: $(date)"
echo ""

# Step 2: Check required files
echo "📋 Step 2: Checking required files..."

if [ ! -f ".env" ]; then
    echo -e "${RED}✗${NC} .env file not found!"
    echo "  Please create .env from .env.example"
    exit 1
else
    echo -e "${GREEN}✓${NC} .env file found"
fi

if [ ! -f "firebase-credentials.json" ]; then
    echo -e "${YELLOW}⚠${NC} firebase-credentials.json not found"
    echo "  Firebase uploads will not work"
else
    echo -e "${GREEN}✓${NC} firebase-credentials.json found"
fi

if [ ! -f "docker-compose.yml" ]; then
    echo -e "${RED}✗${NC} docker-compose.yml not found!"
    exit 1
else
    echo -e "${GREEN}✓${NC} docker-compose.yml found"
fi

echo ""

# Step 3: Stop existing containers
echo "🛑 Step 3: Stopping existing containers..."
docker-compose down 2>/dev/null || true
echo -e "${GREEN}✓${NC} Containers stopped"
echo ""

# Step 4: Build and start containers
echo "🏗️  Step 4: Building and starting containers..."
docker-compose up -d --build

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Containers started successfully"
else
    echo -e "${RED}✗${NC} Failed to start containers"
    exit 1
fi

echo ""

# Step 5: Wait for services to be ready
echo "⏳ Step 5: Waiting for services to start..."
sleep 5

# Check if containers are running
RUNNING=$(docker-compose ps --services --filter "status=running" | wc -l)
TOTAL=$(docker-compose ps --services | wc -l)

if [ "$RUNNING" -eq "$TOTAL" ]; then
    echo -e "${GREEN}✓${NC} All $TOTAL services are running"
else
    echo -e "${YELLOW}⚠${NC} Only $RUNNING/$TOTAL services are running"
fi

echo ""

# Step 6: Verify time sync
echo "🕐 Step 6: Verifying container time..."
HOST_TIME=$(date +%s)
CONTAINER_TIME=$(docker exec zentrya_api date +%s 2>/dev/null || echo "0")

if [ "$CONTAINER_TIME" != "0" ]; then
    TIME_DIFF=$((HOST_TIME - CONTAINER_TIME))
    TIME_DIFF_ABS=${TIME_DIFF#-}  # Absolute value
    
    if [ $TIME_DIFF_ABS -lt 5 ]; then
        echo -e "${GREEN}✓${NC} Container time is synced (diff: ${TIME_DIFF}s)"
    else
        echo -e "${YELLOW}⚠${NC} Container time differs by ${TIME_DIFF}s"
        echo "  This might cause JWT/R2 errors!"
    fi
    
    echo "  Host time:      $(date)"
    echo "  Container time: $(docker exec zentrya_api date 2>/dev/null)"
else
    echo -e "${YELLOW}⚠${NC} Could not check container time"
fi

echo ""

# Step 7: Show service status
echo "📊 Step 7: Service Status"
echo "=========================="
docker-compose ps
echo ""

# Step 8: Show access URLs
echo "🌐 Access Points:"
echo "  API:          http://localhost:8000"
echo "  API Docs:     http://localhost:8000/docs"
echo "  Adminer:      http://localhost:8080"
echo "  Dashboard:    http://localhost:5173 (if running)"
echo ""

# Step 9: Show logs command
echo "📝 To view logs:"
echo "  docker-compose logs -f api"
echo ""

# Step 10: Final checks
echo "🔍 Final Checks:"

# Check if API is responding
sleep 2
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} API is responding"
else
    echo -e "${YELLOW}⚠${NC} API not responding yet (might still be starting)"
fi

# Check database connection
if docker exec zentrya_postgres pg_isready -U postgres > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Database is ready"
else
    echo -e "${YELLOW}⚠${NC} Database not ready"
fi

# Check Redis
if docker exec zentrya_redis redis-cli ping > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Redis is ready"
else
    echo -e "${YELLOW}⚠${NC} Redis not ready"
fi

echo ""
echo "=========================================="
echo -e "${GREEN}✨ Zentrya Platform is running! ✨${NC}"
echo "=========================================="
echo ""
echo "💡 Tips:"
echo "  - Upload files through: http://localhost:8000/docs"
echo "  - Check logs: docker-compose logs -f"
echo "  - Stop platform: docker-compose down"
echo "  - Restart: ./start.sh"
echo ""