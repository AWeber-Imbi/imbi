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
git submodule update --init --recursive
cd api
make setup
cd ..
make setup
cd ui
yarn serve
cd api # in a new terminal
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
- `clean` - Remove all build artifacts and shutdown the docker-compose development environment
- `dist` - Create the release packages
- `env` - Setup a Python virtual environment and install the API dependencies (including testing)
- `setup` - Setup the development environment for the API, OpenAPI docs, and UI

### Testing Targets

The following [Makefile]() targets are for running the various tests for the various parts of Imbi.

- `all-tests` - Runs all tests (API, DDL, OpenAPI Spec, UI)
- `python-tests` - Run the tests for the Python project (bandit, flake8, coverage)
- `bandit` - Run bandit against the Python project
- `coverage` - Use coverage to run the Python project tests
- `flake8` - Run flake8 against the Python project
- `openapi-validate` - Run `swagger-cli validate` against the OpenAPI spec

## Code Formatting

Please ensure your code-style passes the lint tests for the code you are modifying. Code that does not pass lint tests, unit tests, or acceptance tests will not be merged.

Python code is expected to be strict PEP-8 and the `make flake8` command will check the formatting along with other code style preferences.

You should always run prettier for the JavaScript/JSX code. It will reformat the code to the preferred style.

## Local Development Notes

### Adding a new user

The easiest way to add a new user is to create a LDIF file and run it using `docker-compose ldap ldapmodify`:

    $ docker-compose exec ldap ldapadd -D cn=admin,dc=example,dc=org -W
    Enter LDAP Password: admin
    dn: cn=dave-shawley,ou=users,dc=example,dc=org
    objectclass: person
    objectclass: organizationalPerson
    objectclass: inetOrgPerson
    objectClass: posixAccount
    objectClass: shadowAccount
    cn: dave-shawley
    givenName: Dave Shawley
    sn: Dave
    uid: dave-shawley
    mail: daveshawley@gmail.com
    uidNumber: 502
    gidNumber: 501
    homeDirectory: /home/dave-shawley
    loginShell: /bin/ksh
    title: Software Engineer
    initials: DS
    displayName: Dave
    gecos: dave-shawley
    userPassword: {SHA}5en6G6MezRroT3XKqkdPOmY/BfQ=
    ^D
    $

You can also use `docker-compose exec` to spawn a shell and use the ldap utilities directly on the container. The admin
user is `cn=admin,dc=example,dc=org` with a password of `admin`. The `userPassword` in the document is the Base-64
encoded SHA1 checksum of the plaintext password.

Once you have the new user in LDAP, you can log into imbi using the `cn` of the user and the password.

### Configuring gitlab connection

The connection between imbi and gitlab is represented as a OAuth 2 application inside of gitlab and an integration
inside of imbi.  The first thing that you need to do is create the OAuth 2 application in your gitlab account.

1. Log in to your gitlab instance, browse to your profile, and select "Applications" from the nav bar (e.g.,
   https://gitlab.com/oauth/applications)
2. Add a new application with the following information:
   - **Name**: Imbi
   - **Redirect URI**: http://127.0.0.1:8000/gitlab/auth
   - **Confidential**: checked
   - **Scopes**: api
3. Press the **Save Application** button
4. Leave this page open, you will need the two IDs that were generated
5. Generate an API token in imbi if you do not have one
6. Send the following `POST` to imbi to create the integration:

       curl -H "Private-Token: $IMBI_TOKEN" \
            --request POST \
            -d 'api_endpoint=https://gitlab.com/api/v4' \
            -d 'authorization_endpoint=https://gitlab.com/oauth/authorize' \
            -d 'callback_url=http://127.0.0.1:8000/gitlab/auth' \
            -d "client_id=$GITLAB_APPLICATION_ID" \
            -d "client_secret=$GITLAB_SECRET" \
            -d 'name=gitlab' \
            -d 'public_client=false' \
            -d 'revoke_endpoint' \
            -d 'token_endpoint=https://gitlab.com/oauth/token' \
            http://127.0.0.1:8000/integrations

   Assuming that `$IMBI_TOKEN`, `$GITLAB_APPLICATION_ID`, and `$GITLAB_SECRET` are set to the obvious values.
7. After creating the integration, press the "" button on http://127.0.0.1:8000/ui/user/profile .  It will walk through
   the authorization flow for imbi, create the OAuth 2 token, save it in the database, and leave your user in the
   connected state.

# Releasing a new version

## DDL Updates

Database schema updates may be required for the API or other tests to pass. To release a new DDL version, tag the GitHub DDL repository to create a new docker tag that will be picked up by the api docker-compose file.

## Main Release Process

1. Update the VERSION file in imbi-api manually
2. Update submodules and tag the release

```bash
git submodule update --remote --merge
git commit -m 'Release version [VERSION]' -a
git push origin main
git tag [VERSION]
git push origin [VERSION]
```

GitHub Actions will perform all the build steps including:

- Creating the production UI build
- Copy the UI build into the Python project and build the Python package
- Upload the Python package to PyPI
- Create the Docker image and upload it to Docker Hub
