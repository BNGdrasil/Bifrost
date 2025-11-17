#!/bin/bash
# --------------------------------------------------------------------------
# Run tests in Docker environment
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------

set -e

echo "🐳 Starting Docker Compose test environment..."

# Clean up any previous containers
docker-compose -f docker-compose.test.yml down -v

# Build and start services
docker-compose -f docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from bifrost-test

# Clean up
echo "🧹 Cleaning up..."
docker-compose -f docker-compose.test.yml down -v

echo "✅ Tests completed!"
