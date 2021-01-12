#!/bin/sh -e
echo "Setting up tests"
apk --update add curl-dev gcc git libffi-dev libpq libressl-dev make musl-dev postgresql-dev linux-headers tzdata
cp -R /source/ddl /tmp/test/
cp -R /source/imbi /tmp/test/
cp -R /source/scaffolding /tmp/test/
cp -R /source/tests /tmp/test/
cp /source/setup.* /tmp/test/
cp /source/Makefile /tmp/test/
cd /tmp/test
ln -s /usr/local /tmp/test/env
cat > .env <<EOF
export ENVIRONMENT=development
export LDAP_ENABLED=true
export LDAP_HOST=ldap
export LDAP_PORT=389
export LDAP_SSL=False
export LDAP_GROUPS_DN=ou=groups,dc=example,dc=org
export LDAP_USERS_DN=ou=users,dc=example,dc=org
export LDAP_USERNAME=cn
export LDAP_POOLSIZE=5
export SESSION_REDIS_URL=redis://redis:6379/0
export STATS_REDIS_URL=redis://redis:6379/1
export POSTGRES_URL=postgres://postgres@postgres:5432/postgres
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
pip3 install -e '.[testing]'
make python-tests
