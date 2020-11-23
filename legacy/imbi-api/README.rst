Imbi
====
Imbi is a DevOps Service Management Platform designed to provide an efficient
way to manage a large environment that contains many services and applications.

Planned Features
----------------

- Automation of new project setup
    - Source code repository setup
    - Automated initial project creation using curated project cookie-cutters
    - Grafana dashboard creation using curated dashboard cookie-cutters
    - for Consul, Sentry, and other 3rd party integrations
- Centralized Service inventory with:
    - Automated service library/package inventory
    - Service dependency graph
- Automated release management
    - Integrated with releases from GitLab
    - Centralized logging of deployments with per service history and Slack integration
    - Acceptance testing on deployment for projects and first-tier dependencies
- Reporting
    - Site-wide and team specific reporting for service standards and compliance
    - Integration with Consul, Sensu, and PagerDuty for service status and availability history

Environment Variables
---------------------
Imbi runtime configuration is configured by way of environment variables. The following

- ``LDAP_ENABLED``: Use LDAP in addition to internal user management
- ``LDAP_HOST``: The hostname of the server to connect to (Default: ``localhost``)
- ``LDAP_PORT``: The port to connect on (Default: ``389``)
- ``LDAP_SSL``: Indicates whether SSL is enabled for connecting (Default: ``False``)
- ``LDAP_GROUP_OT``: The object type to use for groups (Default: ``groupOfNames``)
- ``LDAP_GROUPS_DN``: The base DN to use for group searching
- ``LDAP_USER_OT``: The object type to use for users (Default: ``inetOrgPerson``)
- ``LDAP_USERS_DN``: The base DN to use for user searching
- ``LDAP_USERNAME``: The username attribute used in user searching (Default: ``uid``)
- ``LDAP_POOL_SIZE``: The size to allocate for the ThreadPoolExecutor for the LDAP interface (Default: ``5``)
- ``POSTGRES_URL``: The Postgres server to (Default: ``postgres://imbi@localhost:5432/imbi``)
- ``SESSION_POOL_SIZE``: The maximum number of redis connections to use for the session pool (Default: ``10``)
- ``SESSION_REDIS_URL``: The Redis server to use for session storage (Default: ``redis://localhost:6379/0``)
- ``STATS_POOL_SIZE``: The maximum number of redis connections to use for the stats pool (Default: ``10``)
- ``STATS_REDIS_URL``: The Redis server to use for Stats storage (Default: ``redis://localhost:6379/1``)

Building Static Assets
----------------------
Imbi uses npm and gulp to build the static assets for the site. Ensure you
have a current version of nodejs and Python 2.7 available to build the
JavaScript and CSS.

.. code-block:: sh

    make ui

Running in Development
----------------------
Perform the following steps to run Imbi in the foreground in your development
environment.

.. code-block:: sh

    make setup
    source env/bin/activate
    source build/test-environment
    imbi

Once complete, imbi should be running at `http://localhost:8000`. The test admin
user is `test` and the password is `password`.

Etymology
---------
Imbi is Old High German for "Swarm of Bees"
