#!/bin/sh -e
echo "Setting up tests"
apk --update add curl-dev gcc git libffi-dev libpq libressl-dev make musl-dev postgresql-dev linux-headers tzdata
cd /tmp/test
tar c -C /source -f - \
    LICENSE \
    MANIFEST.in \
    Makefile \
    VERSION \
    bootstrap \
    docker-compose.yml \
    ddl \
    imbi \
    scaffolding \
    setup.cfg \
    setup.py \
    tests \
  | tar xf -

cat > .env <<EOF
export DEBUG=1
EOF

cat > build/test.yaml <<EOF
---
ldap:
  enabled: true
  host: ldap
  port: 389
  ssl: false
  groups_dn: ou=groups,dc=example,dc=org
  users_dn: ou=users,dc=example,dc=org
  username: cn
  pool_size: 5
postgres:
  url: postgres://postgres@postgres:5432/postgres
session:
  redis_url: redis://redis:6379/0
stats:
  redis_url: redis://redis:6379/1
logging:
  version: 1
  formatters:
    verbose:
      format: "%(levelname) -10s %(asctime)s %(name) -20s %(funcName) -25s: %(message)s"
      datefmt: "%Y-%m-%d %H:%M:%S"
  handlers:
    console:
      class: logging.StreamHandler
      formatter: verbose
  loggers: {}
  root:
    level: CRITICAL
    propagate: true
    handlers: [console]
  disable_existing_loggers: true
  incremental: false
EOF
ls -al
make python-tests
