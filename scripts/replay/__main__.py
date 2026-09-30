"""Command line: ``uv run python -m scripts.replay <command>``.

Commands:

- ``token``: sign an access token for a user, with the JWT secret of
  the API.
- ``record``: send a request for each ``GET`` route, and save the
  responses.
- ``scenarios``: run the write scenarios, and save the responses.
- ``replay``: send the requests of a recording to another API.
- ``diff``: compare two recordings.
- ``timings``: p50 and p95 per route of two recordings.
"""

import argparse
import datetime
import fnmatch
import json
import os
import pathlib
import secrets
import sys
import typing

import httpx
import jwt
import psycopg

from scripts.replay import (
    client,
    diff,
    models,
    plan,
    scenarios,
    sources,
    store,
    templates,
    timings,
)

CONFIG = pathlib.Path(__file__).parent


def _variables(pairs: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for pair in pairs:
        name, separator, value = pair.partition('=')
        if not separator or not name:
            raise SystemExit(f'--var needs name=value, not {pair!r}')
        result[name] = value
    return result


def _token(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f'set the environment variable {name}')
    return value


def _config_dir(arguments: argparse.Namespace) -> pathlib.Path:
    return typing.cast('pathlib.Path', arguments.config_dir)


def _owners(directory: pathlib.Path) -> models.OwnersConfig:
    return models.load_toml(models.OwnersConfig, directory / 'owners.toml')


def _moves(arguments: argparse.Namespace) -> list[models.Move]:
    if not arguments.path_map:
        return []
    path = typing.cast('pathlib.Path', arguments.path_map)
    return models.load_toml(models.PathMapConfig, path).move


def _globals(
    database: sources.Database | None,
    config: models.RoutesConfig,
    overrides: dict[str, str],
) -> dict[str, str]:
    variables: dict[str, str] = {}
    if database is not None:
        for name in config.globals.sources:
            rows = database.fetch(config.sources[name], variables, 1)
            if rows:
                variables.update(rows[0])
    variables.update(overrides)
    return variables


def _openapi(location: str) -> dict[str, typing.Any]:
    if location.startswith(('http://', 'https://')):
        response = httpx.get(location, timeout=60, trust_env=False)
        response.raise_for_status()
        return typing.cast('dict[str, typing.Any]', response.json())
    return typing.cast(
        'dict[str, typing.Any]', json.loads(pathlib.Path(location).read_text())
    )


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def command_token(arguments: argparse.Namespace) -> int:
    secret = _token(arguments.secret_env)
    subject = typing.cast('str | None', arguments.subject)
    if subject is None:
        if not arguments.dsn:
            raise SystemExit('give --subject or --dsn')
        config = models.load_toml(
            models.RoutesConfig, _config_dir(arguments) / 'routes.toml'
        )
        database = sources.Database(arguments.dsn, config.graph)
        try:
            rows = database.fetch(config.sources['admin_email'], {}, 1)
        finally:
            database.close()
        if not rows:
            raise SystemExit('the database has no active admin user')
        subject = rows[0]['admin_email']
    now = datetime.datetime.now(datetime.UTC)
    claims = {
        'sub': subject,
        'jti': secrets.token_urlsafe(16),
        'type': 'access',
        'iat': now,
        'exp': now + datetime.timedelta(seconds=arguments.ttl),
    }
    sys.stdout.write(jwt.encode(claims, secret, algorithm='HS256') + '\n')
    return 0


def command_record(arguments: argparse.Namespace) -> int:
    directory = _config_dir(arguments)
    config = models.load_toml(models.RoutesConfig, directory / 'routes.toml')
    owners = _owners(directory)
    document = _openapi(
        arguments.openapi or f'{arguments.base_url.rstrip("/")}/openapi.json'
    )
    database = sources.Database(arguments.dsn, config.graph)
    try:
        variables = _globals(database, config, _variables(arguments.var))

        def fetch(name: str, limit: int) -> list[dict[str, str]]:
            try:
                return database.fetch(config.sources[name], variables, limit)
            except psycopg.Error as error:
                raise SystemExit(f'source {name!r}: {error}') from error

        built = plan.build(document, config, fetch, variables, arguments.cap)
    finally:
        database.close()
    for route, reason in sorted(built.uncovered.items()):
        sys.stderr.write(f'uncovered: {route}: {reason}\n')
    if built.uncovered and not arguments.allow_uncovered:
        sys.stderr.write('stop: some routes have no requests\n')
        return 2
    requests = [
        request
        for request in built.requests
        if fnmatch.fnmatchcase(request.route, arguments.route)
    ]
    api = client.Client(arguments.base_url, _token(arguments.token_env))
    exchanges: list[models.Exchange] = []
    try:
        for request in requests:
            exchanges.append(
                client.capture(
                    api,
                    key=request.key,
                    kind='get',
                    route=request.route,
                    method='GET',
                    path=request.path,
                    query=request.query,
                    repeat=arguments.repeat,
                    placeholder=request.placeholder,
                )
            )
    finally:
        api.close()
    unowned = sorted(
        {
            exchange.route
            for exchange in exchanges
            if exchange.route not in owners.routes
        }
    )
    store.write(
        arguments.out,
        exchanges,
        {
            'command': 'record',
            'base_url': arguments.base_url,
            'recorded_at': _now(),
            'variables': variables,
            'skipped': built.skipped,
            'uncovered': built.uncovered,
            'unowned_routes': unowned,
            'repeat': arguments.repeat,
        },
    )
    sys.stdout.write(
        f'recorded {len(exchanges)} requests for '
        f'{len({item.route for item in exchanges})} routes; '
        f'skipped {len(built.skipped)} routes; '
        f'{len(built.uncovered)} uncovered; '
        f'{len(unowned)} routes without an owner\n'
    )
    return 0


def command_replay(arguments: argparse.Namespace) -> int:
    source = typing.cast('pathlib.Path', arguments.source)
    recorded = [item for item in store.read(source) if item.kind == 'get']
    meta = store.read_meta(source)
    variables = {
        **typing.cast('dict[str, str]', meta.get('variables', {})),
        **_variables(arguments.var),
    }
    moves = _moves(arguments)
    api = client.Client(arguments.base_url, _token(arguments.token_env))
    exchanges: list[models.Exchange] = []
    try:
        for item in recorded:
            if not fnmatch.fnmatchcase(item.route, arguments.route):
                continue
            path = templates.move(moves, item.method, item.path, variables)
            exchanges.append(
                client.capture(
                    api,
                    key=item.key,
                    kind='get',
                    route=item.route,
                    method=item.method,
                    path=path,
                    query=item.query,
                    repeat=arguments.repeat,
                    placeholder=item.placeholder,
                )
            )
    finally:
        api.close()
    store.write(
        arguments.out,
        exchanges,
        {
            'command': 'replay',
            'base_url': arguments.base_url,
            'recorded_at': _now(),
            'source': str(source),
            'variables': variables,
            'repeat': arguments.repeat,
        },
    )
    sys.stdout.write(f'replayed {len(exchanges)} requests\n')
    return 0


def command_scenarios(arguments: argparse.Namespace) -> int:
    directory = _config_dir(arguments)
    owners = _owners(directory)
    overrides = _variables(arguments.var)
    if arguments.variables_from:
        meta = store.read_meta(arguments.variables_from)
        overrides = {
            **typing.cast('dict[str, str]', meta.get('variables', {})),
            **overrides,
        }
    database = None
    config = models.load_toml(models.RoutesConfig, directory / 'routes.toml')
    if arguments.dsn:
        database = sources.Database(arguments.dsn, config.graph)
    try:
        variables = _globals(database, config, overrides)
    finally:
        if database is not None:
            database.close()
    variables.setdefault('run', arguments.run_token)
    files = [
        item
        for item in scenarios.load(directory / 'scenarios')
        if fnmatch.fnmatchcase(item.domain, arguments.domain)
    ]
    api = client.Client(arguments.base_url, _token(arguments.token_env))
    runner = scenarios.Runner(
        client=api,
        routes=templates.RouteTable(tuple(owners.routes)),
        variables=variables,
        moves=_moves(arguments),
    )
    try:
        exchanges, outcomes = runner.run(files)
    finally:
        api.close()
    failures = [
        failure for outcome in outcomes for failure in outcome.failures
    ]
    store.write(
        arguments.out,
        exchanges,
        {
            'command': 'scenarios',
            'base_url': arguments.base_url,
            'recorded_at': _now(),
            'variables': variables,
            'failures': failures,
        },
    )
    for failure in failures:
        sys.stderr.write(f'failed: {failure}\n')
    sys.stdout.write(
        f'ran {len(outcomes)} scenarios ({len(exchanges)} steps); '
        f'{sum(1 for item in outcomes if item.failures)} failed\n'
    )
    return 1 if failures and not arguments.allow_failures else 0


def _read_all(directories: list[pathlib.Path]) -> list[models.Exchange]:
    return [
        exchange
        for directory in directories
        for exchange in store.read(directory)
    ]


def command_diff(arguments: argparse.Namespace) -> int:
    directory = _config_dir(arguments)
    rules = models.load_toml(
        models.NormalizeConfig, directory / 'normalize.toml'
    ).rule
    expected = [
        models.load_toml(models.ExpectedConfig, path)
        for path in sorted((directory / 'expected').glob('*.toml'))
    ]
    differ = diff.Differ(
        rules=rules,
        expected=expected,
        owners=_owners(directory),
        mask_unstable=arguments.mask_unstable,
    )
    report = differ.run(_read_all(arguments.old), _read_all(arguments.new))
    values = not arguments.no_values
    sys.stdout.write(diff.format_text(report, values=values))
    if arguments.json:
        output = typing.cast('pathlib.Path', arguments.json)
        output.write_text(
            json.dumps(
                {
                    'compared': report.compared,
                    'unexpected': {
                        owner: [item.as_dict(values=values) for item in items]
                        for owner, items in report.by_owner().items()
                    },
                    'expected': [
                        item.as_dict(values=values) for item in report.expected
                    ],
                    'unused_expectations': report.unused_expectations,
                    'unstable': report.unstable,
                },
                indent=2,
                default=str,
            )
        )
    return 1 if report.unexpected else 0


def command_timings(arguments: argparse.Namespace) -> int:
    rows = timings.compare(_read_all(arguments.old), _read_all(arguments.new))
    sys.stdout.write(timings.format_markdown(rows, arguments.threshold))
    return 0


def _add_compare_commands(
    add_parser: typing.Callable[..., argparse.ArgumentParser],
) -> None:
    compare = add_parser('diff', help='compare two recordings')
    compare.add_argument('--old', type=pathlib.Path, nargs='+', required=True)
    compare.add_argument('--new', type=pathlib.Path, nargs='+', required=True)
    compare.add_argument('--json', type=pathlib.Path)
    compare.add_argument(
        '--no-values',
        action='store_true',
        help='show the pointers only, not the values',
    )
    compare.add_argument(
        '--mask-unstable',
        action='store_true',
        help=(
            'also mask the fields that changed between two sends (from '
            '--repeat); for a first look only, because it is not a rule'
        ),
    )
    compare.set_defaults(handler=command_diff)

    timing = add_parser('timings', help='p50 and p95 per route')
    timing.add_argument('--old', type=pathlib.Path, nargs='+', required=True)
    timing.add_argument('--new', type=pathlib.Path, nargs='+', required=True)
    timing.add_argument('--threshold', type=float, default=1.2)
    timing.set_defaults(handler=command_timings)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog='python -m scripts.replay')
    root.add_argument(
        '--config-dir',
        type=pathlib.Path,
        default=CONFIG,
        help='the directory with routes.toml, owners.toml, and so on',
    )
    commands = root.add_subparsers(dest='command', required=True)

    def api_options(command: argparse.ArgumentParser) -> None:
        command.add_argument('--base-url', required=True)
        command.add_argument(
            '--token-env',
            default='REPLAY_TOKEN',
            help='the environment variable with the bearer token',
        )
        command.add_argument('--out', type=pathlib.Path, required=True)
        command.add_argument(
            '--var', action='append', default=[], help='name=value'
        )

    token = commands.add_parser('token', help='sign an access token')
    token.add_argument('--secret-env', default='IMBI_AUTH_JWT_SECRET')
    token.add_argument('--subject', help='the user email')
    token.add_argument('--dsn', help='use the first active admin user')
    token.add_argument('--ttl', type=int, default=86400)
    token.set_defaults(handler=command_token)

    record = commands.add_parser('record', help='record every GET route')
    api_options(record)
    record.add_argument('--dsn', required=True)
    record.add_argument('--openapi', help='a file or URL')
    record.add_argument('--cap', type=int, default=10)
    record.add_argument('--repeat', type=int, default=1)
    record.add_argument('--route', default='*', help='a glob on the route')
    record.add_argument('--allow-uncovered', action='store_true')
    record.set_defaults(handler=command_record)

    replay = commands.add_parser('replay', help='replay a recording')
    api_options(replay)
    replay.add_argument(
        '--from', dest='source', type=pathlib.Path, required=True
    )
    replay.add_argument('--path-map', type=pathlib.Path)
    replay.add_argument('--repeat', type=int, default=1)
    replay.add_argument('--route', default='*', help='a glob on the route')
    replay.set_defaults(handler=command_replay)

    run = commands.add_parser('scenarios', help='run the write scenarios')
    api_options(run)
    run.add_argument('--dsn', help='read the global variables here')
    run.add_argument(
        '--variables-from',
        type=pathlib.Path,
        help='use the variables of this recording (the old side)',
    )
    run.add_argument('--path-map', type=pathlib.Path)
    run.add_argument('--run-token', default='replay')
    run.add_argument('--domain', default='*', help='a glob on the domain')
    run.add_argument('--allow-failures', action='store_true')
    run.set_defaults(handler=command_scenarios)

    _add_compare_commands(commands.add_parser)
    return root


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    handler = typing.cast(
        'typing.Callable[[argparse.Namespace], int]', arguments.handler
    )
    return handler(arguments)


if __name__ == '__main__':
    sys.exit(main())
