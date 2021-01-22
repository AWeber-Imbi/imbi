Imbi
====
Imbi is a DevOps Service Management Platform designed to provide an efficient
way to manage a large environment that contains many services and applications.

|Version| |Status| |Coverage| |License|

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
imbi uses a YAML based configuration file. See the `example <example.yaml>`_
file for available configuration options.

Contributing
------------
For information on contributing, including development environment setup, see
`CONTRIBUTING.md <CONTRIBUTING.md>`_.

Etymology
---------
Imbi is Old High German for "Swarm of Bees"

.. |Version| image:: https://img.shields.io/pypi/v/aiorabbit.svg?
   :target: https://pypi.python.org/pypi/aiorabbit

.. |Status| image:: https://github.com/aweber/imbi/workflows/Testing/badge.svg?
   :target: https://github.com/aweber/imbi/actions?workflow=Testing
   :alt: Build Status

.. |Coverage| image:: https://img.shields.io/codecov/c/github/aweber/imbi.svg?
   :target: https://codecov.io/github/aweber/imbi?branch=master

.. |License| image:: https://img.shields.io/pypi/l/aiorabbit.svg?
   :target: https://aiorabbit.readthedocs.org
