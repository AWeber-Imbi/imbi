Imbi
====
Imbi is a DevOps Service Management Platform designed to provide an efficient
way to manage a large environment that contains many services and applications.

|Version| |Coverage| |License|

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

Configuration
-------------
imbi uses a YAML based configuration file. See the `example <https://github.com/aweber/imbi/blob/main/example.yaml>`_
file for available configuration options.

Docker Image
------------
A `Docker image <https://hub.docker.com/r/aweber/imbi>`_ is available as
`aweber/imbi:latest`. Mount your custom config file in as `/etc/imbi/imbi.yaml`.
If you want to put it in a different path, make sure to set the command to run
when running the docker container.

The `docker-compose.yml <https://github.com/aweber/imbi/blob/main/docker-compose.yml>`_
configuration in the repository includes an optional imbi container that you can use for
testing in a containerized environment.

Contributing
------------
For information on contributing, including development environment setup, see
`CONTRIBUTING.md <https://github.com/aweber/imbi/blob/main/CONTRIBUTING.md>`_.

Etymology
---------
Imbi is Old High German for "Swarm of Bees"

.. |Version| image:: https://img.shields.io/pypi/v/imbi.svg
   :target: https://pypi.python.org/pypi/imbi

.. |Coverage| image:: https://img.shields.io/codecov/c/github/aweber/imbi.svg
   :target: https://codecov.io/github/aweber/imbi?branch=master

.. |License| image:: https://img.shields.io/pypi/l/imbi.svg?
   :target: https://imbi.readthedocs.org
