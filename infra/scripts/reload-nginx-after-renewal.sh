#!/usr/bin/env bash
set -euo pipefail
cd /opt/metarest
docker compose --env-file .env -f infra/docker-compose.prod.yml exec -T frontend nginx -t
docker compose --env-file .env -f infra/docker-compose.prod.yml exec -T frontend nginx -s reload
