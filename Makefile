REVISION = $(shell git rev-parse HEAD | cut -b 1-7)

ifneq (,$(wildcard ./.env))
	include .env
	export $(shell sed 's/=.*//' .env)
endif

.PHONY: all
all: setup scaffolding/postgres/ddl.sql build-openapi all-tests build-ui

.PHONY: build-openapi
build-openapi:
	@ cd openapi && yarn run build

.PHONY: build-ui
build-ui:
	@ cd ui && NODE_ENV=production yarn run build

.PHONY: build-ui-dev
build-ui-dev:
	@ cd ui && yarn run dev-build

.PHONY: clean
clean:
	@ docker-compose down
	@ rm -f scaffolding/postgres/ddl.sql
	@ rm -rf imbi/static/fonts/* imbi/static/js/*
	@ rm -rf .env build dist imbi.egg-info env ui/node_modules

.env: scaffolding/postgres/ddl.sql
	@ ./bootstrap

env:
	@ python3 -m venv env
	@ source env/bin/activate && env/bin/pip3 install --upgrade pip
	@ source env/bin/activate && env/bin/pip3 install wheel
	@ source env/bin/activate && env/bin/pip3 install -e '.[testing]'

.PHONY: postgres-ready
postgres-ready: .env
ifeq ($(docker-compose ps postgres |grep -c healthy), 1)
	@ $(error Docker image for PostgreSQL is not running, perhaps you forget to run "make bootstrap" or you should "make clean" and try again)
endif

scaffolding/postgres/ddl.sql:
	@ cd ddl && bin/build.sh ../scaffolding/postgres/ddl.sql

.PHONY: setup
setup: .env env openapi/node_modules ui/node_modules

.PHONY: ddl-setup
ddl-setup: .env

.PHONY: openapi-setup
openapi-setup: openapi/node_modules

.PHONY: python-setup
python-setup: .env env

.PHONY: ui-setup
ui-setup: ui/node_modules

.PHONY: dist
dist: openapi-setup ui-setup
	@ rm -rf dist
	@ cd openapi && yarn run build
	@ cd ui && NODE_ENV=production yarn run build
	@ cd ddl && bin/build.sh ../ddl.sql
	@ python3 setup.py sdist

openapi/node_modules:
	@ cd openapi && yarn install

ui/node_modules:
	@ cd ui && yarn install

.PHONY: watch
watch: ui/node_modules
	@ cd ui && yarn run watch

# Testing

.PHONEY: bandit
bandit: env
	@ printf "\nRunning Bandit\n\n"
	@ env/bin/bandit -r imbi

.PHONY: coverage
coverage: .env env
	@ printf "\nRunning Python Tests\n\n"
	@ env/bin/coverage run
	@ env/bin/coverage xml
	@ env/bin/coverage report

.PHONY: depcheck
depcheck: ui/node_modules
	@ printf "\nRunning depcheck\n\n"
	@ cd ui && yarn run depcheck

.PHONY: eslint
eslint: ui/node_modules
	@ printf "\nRunning eslint\n\n"
	@ cd ui && yarn run eslint

.PHONY: flake8
flake8: env
	@ printf "\nRunning Flake8 Tests\n\n"
	@ flake8 --tee --output-file=build/flake8.txt

.PHONY: jest
jest: ui/node_modules
	@ printf "\nRunning jest\n\n"
	@ cd ui && yarn run test-coverage

.PHONY: openapi-validate
openapi-validate:
	@ printf "\nRunning swagger-cli-validate\n\n"
	@ cd openapi && yarn run validate

.PHONY: jest
prettier-check: ui/node_modules
	@ printf "\nRunning prettier\n\n"
	@ cd ui && yarn run prettier-check

# Testing Groups

.PHONY: all-tests
all-tests: ddl-tests python-tests ui-tests

.PHONY: ddl-tests
ddl-tests: postgres-ready
	@ printf "\nRunning DDL Tests\n\n"
	@ docker-compose exec -T postgres /usr/bin/dropdb --if-exists ${REVISION}
	@ docker-compose exec -T postgres /usr/bin/createdb ${REVISION} > /dev/null
	@ cd ddl && bin/build.sh ../build/ddl-${REVISION}.sql
	@ docker-compose exec -T postgres /usr/bin/psql -d ${REVISION} -v ON_ERROR_STOP=1 -f /build/ddl-${REVISION}.sql -X -q --pset=pager=off
	@ docker-compose exec -T postgres /usr/bin/psql -d ${REVISION} -v ON_ERROR_STOP=1 -c "CREATE EXTENSION pgtap;" -X -q --pset=pager=off
	@ cd ddl && docker-compose exec -T postgres /usr/local/bin/pg_prove -v -f -d ${REVISION} tests/*.sql
	@ docker-compose exec -T postgres /usr/bin/dropdb --if-exists  ${REVISION}
	@ rm build/ddl-${REVISION}.sql

.PHONY: python-tests
python-tests: bandit flake8 coverage

.PHONY: ui-tests
ui-tests: ui/node_modules depcheck prettier-check eslint jest
