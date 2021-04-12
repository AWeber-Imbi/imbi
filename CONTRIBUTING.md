# Contributing

## Test Coverage

To contribute to Imbi, please make sure that any new features or changes
to existing functionality **include test coverage**.

*Pull requests that add or change code without coverage have a much lower chance
of being accepted.*

## Prerequisites

Imbi requires the following in the development environment:

- Docker (local)
- Make
- Node
  - yarn
- Python 3.9
    - pip
    - setuptools

It expects to be run in a Unix like environment (Primary development is in MacOS).

## Running in Development

Perform the following steps to run Imbi in the foreground in your development
environment.

```bash
make setup
source env/bin/activate
imbi --debug build/debug.yaml
```

Once complete, imbi should be running at [http://localhost:8000](). The test admin
user is `test` and the password is `password`.


## Building Static Assets

Imbi uses webpack to build the static assets for the site. To work on the UI
in development mode, `make watch` is useful.

## Makefile Targets

The following generic targets are available in the [Makefile]().

- `all` - Setup the development environment, DDL and DML, OpenAPI document, the UI, and run tests
- `bootstrap` - Bootstrap the docker-compose dependencies for development
- `build-openapi` - Build the OpenAPI template document
- `build-ui` - Create a "production" build of the React UI
- `build-ui-dev` - Create a development build of the React UI
- `clean` - Remove all build artifacts and shutdown the docker-compose development environment
- `dist` - Create the release packages
- `env` - Setup a Python virtual environment and install the API dependencies (including testing)
- `setup` - Setup the development environment for the API, OpenAPI docs, and UI
- `serve` - Run a JavaScript webserver that watches UI files and rebuilds the development versions on change, pushing changes to the browser
- `watch` - Watches UI files and rebuilds the development versions on change

### Testing Targets

The following [Makefile]() targets are for running the various tests for the various parts of Imbi.

- `all-tests` - Runs all tests (API, DDL, OpenAPI Spec, UI)
- `ddl-tests` - Run the DDL pgTap tests
- `python-tests` - Run the tests for the Python project (bandit, flake8, coverage)
- `ui-tests` - Run the tests for the UI (eslint, jest)
- `bandit` - Run bandit against the Python project
- `coverage` - Use coverage to run the Python project tests
- `estlint` - Run eslint against the UI project source
- `flake8` - Run flake8 against the Python project
- `jest` - Run jest against the UI project tests
- `openapi-validate` - Run `swagger-cli validate` against the OpenAPI spec

## Code Formatting

Please ensure your code-style passes the lint tests for the code you are modifying. Code that does not pass lint tests, unit tests, or acceptance tests will not be merged.

Python code is expected to be strict PEP-8 and the `make flake8` command will check the formatting along with other code style preferences.

You should always run prettier for the JavaScript/JSX code. It will reformat the code to the preferred style.
