REVISION = $(shell git rev-parse HEAD | cut -b 1-7)

ifneq (,$(wildcard ./.env))
	include .env
	export $(shell sed 's/=.*//' .env)
endif

.PHONY: all
all: setup all-tests

.PHONY: clean
clean:
	@ docker-compose down --remove-orphans --volumes
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
setup: .env env

# Testing

.PHONY: bandit
bandit: env
	@ printf "\nRunning Bandit\n"
	@ env/bin/bandit -r imbi

.PHONY: coverage
coverage: .env env
	@ printf "\nRunning Python Tests\n"
	@ env/bin/coverage run
	@ env/bin/coverage xml
	@ env/bin/coverage report

.PHONY: flake8
flake8: env
	@ printf "\nRunning Flake8 Tests\n"
	@ env/bin/flake8 --tee --output-file=build/flake8.txt

# Testing Groups

.PHONY: test
test: bandit flake8 coverage
