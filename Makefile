REVISION = $(shell git rev-parse HEAD | cut -b 1-7)

.PHONY: all
all: dist

.PHONY: deploy_setup
deploy_setup:
	apt-get install -y python3 curl
	curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py
	python3 get-pip.py --user
	pip3 install --upgrade setuptools twine packaging

.PHONY: setup
setup: openapi/node_modules ui/node_modules

.PHONY: dist
dist: setup
	@ rm -rf api/dist
	@ cd openapi && yarn run build
	@ cp openapi/build/openapi.yaml api/imbi/templates/openapi.yaml
	@ cp openapi/build/redoc.standalone.js api/imbi/static/redoc.standalone.js
	@ cd ui && NODE_ENV=production yarn run build
	@ cp -R ui/build/* api/imbi/static/
	@ cd api && python3 setup.py sdist

openapi/node_modules:
	@ cd openapi && yarn install

ui/node_modules:
	@ cd ui && yarn install
