#!/bin/bash
# Runs once, the first time the database starts: main schema + a separate database for Cognee.
set -e
psql -v ON_ERROR_STOP=1 -U postgres -d postgres -c "CREATE DATABASE cognee_db;"
psql -v ON_ERROR_STOP=1 -U postgres -d cognee_db -c "CREATE EXTENSION IF NOT EXISTS vector;"
for f in /docker-entrypoint-initdb.d/migrations/*.sql; do
  echo "applying $f"
  psql -v ON_ERROR_STOP=1 -U postgres -d postgres -f "$f"
done
