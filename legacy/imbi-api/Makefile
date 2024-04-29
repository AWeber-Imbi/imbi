REVISION = $(shell git rev-parse HEAD | cut -b 1-7)

ifneq (,$(wildcard ./.env))
	-include .env
	export $(shell sed 's/=.*//' .env)
endif

.PHONY: all
all: setup test

.PHONY: clean
clean:
	@ docker compose down --remove-orphans --volumes
	@ rm -rf imbi/static/fonts/* imbi/static/js/*
	@ rm -rf .env build dist imbi.egg-info env ui/node_modules

.env: bootstrap compose.yml
	@ ./bootstrap

env: env/stamp

env/stamp: setup.cfg setup.py Makefile
	@ python3 -m venv env
	@ . ./env/bin/activate && PIP_USER=0 env/bin/pip3 install --upgrade pip
	@ . ./env/bin/activate && PIP_USER=0 env/bin/pip3 install wheel
	@ . ./env/bin/activate && PIP_USER=0 env/bin/pip3 install -e '.[testing]'
	@ test -d .git/ && ./env/bin/pre-commit install --install-hooks || true
	@ touch env/stamp

.PHONY: setup
setup: .env env

# Testing

.PHONY: lint
lint: env
	@ printf "\nRunning pre-commit hooks\n"
	@ env/bin/pre-commit run --all-files

.PHONY: coverage
coverage: .env env
	@ printf "\nRunning Python Tests\n"
	@ env/bin/coverage run
	@ env/bin/coverage xml
	@ env/bin/coverage report

.PHONY: test
test: lint coverage
