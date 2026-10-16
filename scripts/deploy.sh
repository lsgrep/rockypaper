#!/usr/bin/env bash
# Ship the repo to a host and (re)start the stack there.
#   scripts/deploy.sh ubuntu@1.2.3.4                  # HTTP only, port 80
#   PSR_DOMAIN=psr.fin.run scripts/deploy.sh ubuntu@1.2.3.4   # HTTPS via Let's Encrypt
set -euo pipefail

host="${1:?usage: scripts/deploy.sh user@host}"
remote_dir="psr"

rsync -az --delete \
  --exclude .venv --exclude dist --exclude '**/__pycache__' \
  --exclude .pytest_cache --exclude .mypy_cache --exclude .ruff_cache \
  ./ "$host:$remote_dir/"

if [[ -n "${PSR_DOMAIN:-}" ]]; then
  compose="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
  env="PSR_DOMAIN=$PSR_DOMAIN ACME_EMAIL=${ACME_EMAIL:-}"
else
  compose="docker compose"
  env="PSR_HTTP_PORT=80"
fi

ssh "$host" "cd $remote_dir && export $env && $compose up -d --build --remove-orphans && $compose ps"
