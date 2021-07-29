REVISION = $(shell git rev-parse HEAD | cut -b 1-7)

ifneq (,$(wildcard ./.env))
	include .env
	export $(shell sed 's/=.*//' .env)
endif

.PHONY: all
all: setup build-openapi all-tests build-ui

.PHONY: build-openapi
build-openapi: openapi-setup
	@ cd openapi && yarn run build && yarn run redoc

.PHONY: clean
clean:
	@ docker-compose down
	@ rm -rf imbi/static/fonts/* imbi/static/js/*
	@ rm -rf .env build dist imbi.egg-info env ui/node_modules

.env: bootstrap docker-compose.yml
	@ ./bootstrap

env: env/stamp

env/stamp: setup.cfg setup.py
	@ python3 -m venv env
	@ source env/bin/activate && PIP_USER=0 env/bin/pip3 install --upgrade pip
	@ source env/bin/activate && PIP_USER=0 env/bin/pip3 install wheel
	@ source env/bin/activate && PIP_USER=0 env/bin/pip3 install -e '.[testing]'
	@ touch env/stamp

.PHONY: setup
setup: .env env openapi/node_modules ui/node_modules

.PHONY: openapi-setup
openapi-setup: openapi/node_modules

.PHONY: python-setup
python-setup: .env env

.PHONY: dist
dist: build-openapi ui-setup
	@ rm -rf dist
	@ cd openapi && yarn run build
	@ cd ui && NODE_ENV=production yarn run build
	@ python3 setup.py sdist

openapi/node_modules: openapi/package.json
	@ cd openapi && yarn install

# Testing

.PHONY: bandit
bandit: env
	@ printf "\nRunning Bandit\n\n"
	@ env/bin/bandit -r imbi

.PHONY: coverage
coverage: .env env
	@ printf "\nRunning Python Tests\n\n"
	@ env/bin/coverage run
	@ env/bin/coverage xml
	@ env/bin/coverage report

.PHONY: flake8
flake8: env
	@ printf "\nRunning Flake8 Tests\n\n"
	@ env/bin/flake8 --tee --output-file=build/flake8.txt

.PHONY: openapi-validate
openapi-validate:
	@ printf "\nRunning swagger-cli-validate\n\n"
	@ cd openapi && yarn run validate

# Testing Groups

.PHONY: all-tests
all-tests: python-tests

.PHONY: python-tests
python-tests: bandit flake8 coverage
