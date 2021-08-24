"""
Imbi CLI application

"""
import argparse
import base64
import binascii
import logging
import pathlib
import sys
import typing

import yaml
from sprockets import http

from imbi import app, pkgfiles, version
from imbi.endpoints import static

LOGGER = logging.getLogger(__name__)

DEFAULT_LOG_CONFIG = {
    'version': 1,
    'formatters': {
        'verbose': {
            'format':
                '%(levelname) -10s %(asctime)s %(process)-6d '
                '%(name) -20s %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S'
        }
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose'
        }
    },
    'loggers': {
        'imbi': {
            'level': 'INFO'
        },
        'tornado': {
            'level': 'INFO'
        }
    },
    'root': {
        'level': 'WARNING',
        'handlers': ['console']
    },
    'disable_existing_loggers': True,
    'incremental': False
}


def run() -> None:
    args = _parse_cli_args()
    http.run(app.Application, *load_configuration(args.config[0], args.debug))


def load_configuration(config: str, debug: bool) -> typing.Tuple[dict, dict]:
    """Load the configuration file and apply all of the default settings"""
    config_file = pathlib.Path(config)
    if not config_file.exists():
        sys.stderr.write(
            'Configuration file {} not found\n'.format(config))
        sys.exit(1)

    with config_file.open('r') as handle:
        try:
            config = yaml.safe_load(handle)
        except yaml.YAMLError as error:
            sys.stderr.write(
                'Failed to load configuration file: {}\n'.format(error))
            sys.exit(1)
        else:
            if not isinstance(config, dict):
                sys.stderr.write(
                    'Configuration file {} is not a YAML mapping\n'.format(
                        config_file.name))
                sys.exit(1)

    log_config = config.get('logging', DEFAULT_LOG_CONFIG)

    automations = config.get('automations', {})
    automations_gitlab = automations.get('gitlab', {})
    automations_grafana = automations.get('grafana', {})
    if automations_grafana.get('url') \
            and automations_grafana.get('admin_token'):
        automations_grafana['enabled'] = True
    automations_sentry = automations.get('sentry', {})
    if automations_sentry.get('url') \
            and automations_sentry.get('admin_token'):
        automations_sentry['enabled'] = True
    automations_sonar = automations.get('sonarqube', {})
    if automations_sonar.get('url') and automations_sonar.get('admin_token'):
        automations_sonar['enabled'] = True
    footer_link = config.get('footer_link', {})
    http_settings = config.get('http', {})
    ldap = config.get('ldap', {})
    postgres = config.get('postgres', {})
    sentry = config.get('sentry', {})
    session = config.get('session', {})
    stats = config.get('stats', {})

    module_path = pathlib.Path(sys.modules['imbi'].__file__).parent

    # Allow encryption key to be encoded as a Base-64 string.
    # If it isn't, then use it as-is.
    try:
        encoded_key = config['encryption_key']
    except KeyError:
        encryption_key = b'some thirty-two character secret'
    else:
        try:
            encryption_key = base64.b64decode(encoded_key.encode())
        except binascii.Error:
            encryption_key = encoded_key.encode()

    settings = {
        'automations': {
            'gitlab': {
                'project_link_type_id':
                    automations_gitlab.get('project_link_type_id'),
                'restrict_to_user':
                    automations_grafana.get('restrict_to_user', False)
            },
            'grafana': {
                'enabled': automations_grafana.get('enabled', False),
                'project_link_type_id':
                    automations_grafana.get('project_link_type_id')
            },
            # see https://pycqa.github.io/isort/reference/isort/settings.html
            'isort': automations.get('isort', {}),
            'sentry': {
                'enabled': automations_sentry.get('enabled', False),
                'project_link_type_id':
                    automations_sentry.get('project_link_type_id')
            },
            'sonarqube': {
                'enabled': automations_sonar.get('enabled', False),
                'admin_token': automations_sonar.get('admin_token'),
                'project_link_type_id':
                    automations_sonar.get('project_link_type_id'),
                'url': automations_sonar.get('url')
            },
            # see https://github.com/google/yapf#knobs
            'yapf': automations.get('yapf', {}),
        },
        'canonical_server_name': http_settings['canonical_server_name'],
        'compress_response': http_settings.get('compress_response', True),
        'cookie_secret': http_settings.get('cookie_secret', 'imbi'),
        'debug': debug,
        'encryption_key': encryption_key,
        'footer_link': {
            'icon': footer_link.get('icon', ''),
            'text': footer_link.get('text', ''),
            'url': footer_link.get('url', '')
        },
        'frontend_url': config.get('frontend_url', None),
        'javascript_url': config.get('javascript_url', None),
        'ldap': {
            'enabled': ldap.get('enabled'),
            'host': ldap.get('host', 'localhost'),
            'port': ldap.get('port', 636),
            'ssl': ldap.get('ssl', False),
            'pool_size': ldap.get('pool_size', 5),
            'group_member_attr': ldap.get('group_member_dn', 'member'),
            'group_object_type': ldap.get('group_object_type', 'groupOfNames'),
            'groups_dn': ldap.get('groups_dn'),
            'user_object_type': ldap.get('user_object_type', 'inetOrgPerson'),
            'username': ldap.get('username', 'uid'),
            'users_dn': ldap.get('users_dn')
        },
        'number_of_procs': http_settings.get('processes', 2),
        'permissions': [],
        'port': http_settings.get('port', 8000),
        'postgres_url': postgres.get('url'),
        'postgres_max_pool_size': postgres.get('max_pool_size'),
        'postgres_min_pool_size': postgres.get('min_pool_size'),
        'postgres_connection_timeout': postgres.get('connection_timeout'),
        'postgres_connection_ttl': postgres.get('connection_ttl'),
        'postgres_query_timeout': postgres.get('query_timeout'),
        'project_url_template': config.get('project_url_template', None),
        'sentry_backend_dsn': sentry.get('backend_dsn', 'false'),
        'sentry_ui_dsn': sentry.get('ui_dsn', 'false'),
        'server_header': 'imbi/{}'.format(version),
        'session_duration': int(session.get('duration', '7')),
        'session_pool_size': session.get('pool_size', 10),
        'session_redis_url': session.get(
            'redis_url', 'redis://localhost:6379/0'),
        'static_handler_class': static.StaticFileHandler,
        'static_path': module_path / 'static',
        'stats_pool_size': stats.get('pool_size', 10),
        'stats_redis_url': stats.get(
            'redis_url', 'redis://localhost:6379/1'),
        'template_loader': pkgfiles.TemplateLoader(debug=debug),
        'template_path': module_path / 'templates',
        'version': version,
        'xheaders': http_settings.get('xheaders', True),
        'xsrf_cookies': False,
    }

    return {k: v for k, v in settings.items() if v is not None}, log_config


def _parse_cli_args() -> argparse.Namespace:
    """Create the CLI parser and parse the CLI arguments"""
    parser = argparse.ArgumentParser(
        'Imbi',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument(
        '--debug', action='store_true', help='Enable debug mode')
    parser.add_argument('-V', '--version', action='version', version=version)
    parser.add_argument(
        'config', metavar='CONFIG FILE', nargs=1,
        help='Configuration File')
    return parser.parse_args()
