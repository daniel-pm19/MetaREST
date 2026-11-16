#!/usr/bin/env bash
# Run on the deployment host with an instance role granting s3:PutObject.
set -euo pipefail
umask 077
cd /opt/metarest
: "${BACKUP_BUCKET:?Set BACKUP_BUCKET to the S3 bucket name}"
archive="$(mktemp /tmp/metarest-backup.XXXXXX.gz)"
trap 'rm -f "$archive"' EXIT
docker compose --env-file .env -f infra/docker-compose.prod.yml exec -T mongo sh -c \
  'mongodump --username "$MONGO_INITDB_ROOT_USERNAME" --password "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --db metarest --archive --gzip' > "$archive"
aws s3 cp "$archive" "s3://${BACKUP_BUCKET}/metarest/$(date -u +%Y-%m-%dT%H-%M-%SZ).archive.gz" --only-show-errors
