#!/bin/bash
# docker_cleanup.sh - Remove all dangling Docker images and prune system

set -e

echo "Removing all dangling Docker images..."
docker images -f "dangling=true" -q | xargs -r docker rmi -f

echo "Running docker system prune..."
docker system prune -f

echo "Docker cleanup complete."
