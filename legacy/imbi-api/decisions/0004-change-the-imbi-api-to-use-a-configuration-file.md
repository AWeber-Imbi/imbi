# 4. Change the imbi API to use a configuration file

Date: 2021-01-21

## Status

Accepted

## Context

Imbi has been created using principles laid out in [12 Factor App](https://12factor.net/)
methodology. In the spirit of starting small and evolving over time, environment
variables were chosen as the way that the application was configured. As the
application has grown, the number of environment variables required for configuration
has significantly increased, and will continue to do so.

## Decision

To simplify configuration, I have decided to move to a single configuration file,
using YAML as the file format. The document will be structured into key sections
to provide logical groupings of configuration values.

## Consequences

While the single file configuration approach will make it easier to configure
Imbi in the long term, existing code and documentation will need to be updated.
