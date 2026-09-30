"""The ``imbi-common`` command: ``imbi-common etl run`` and ``reconcile``.

The target URL is the ``imbi_maintenance`` login. No application reads
it: it is an option here, or ``IMBI_ETL_TARGET_URL`` so that the
password is not on the command line. The source URL reads the graph;
at the cutover it is the same database.
"""

import asyncio
import json
import pathlib
import sys
import typing

import psycopg
import typer

from imbi.common.db.etl import mapping, reconcile, runner

main = typer.Typer(no_args_is_help=True)
etl = typer.Typer(no_args_is_help=True, help='Graph to relational ETL.')
main.add_typer(etl, name='etl')

SourceUrl = typing.Annotated[
    str,
    typer.Option(
        envvar='IMBI_ETL_SOURCE_URL',
        help='PostgreSQL URL of the database with the AGE graph.',
    ),
]
TargetUrl = typing.Annotated[
    str,
    typer.Option(
        envvar='IMBI_ETL_TARGET_URL',
        help='PostgreSQL URL of the relational database, as imbi_maintenance.',
    ),
]
Graph = typing.Annotated[
    str, typer.Option(help='The AGE graph name (its schema).')
]
TenantSlug = typing.Annotated[
    str, typer.Option(help='Slug of the one tenant (Appendix E, E2).')
]
TenantName = typing.Annotated[
    str, typer.Option(help='Name of the one tenant (Appendix E, E2).')
]


@etl.command('run')
def run_command(
    source_url: SourceUrl,
    target_url: TargetUrl,
    graph: Graph = 'imbi',
    tenant_slug: TenantSlug = 'default',
    tenant_name: TenantName = 'Default',
    allow_pending: typing.Annotated[
        bool,
        typer.Option(
            help='Run although some tables have no mapping yet. They are'
            ' truncated and stay empty. For tests and rehearsals only.'
        ),
    ] = False,
    dry_run: typing.Annotated[
        bool,
        typer.Option(help='Write the rows as JSON lines and insert nothing.'),
    ] = False,
    output: typing.Annotated[
        pathlib.Path | None,
        typer.Option(help='Where --dry-run writes. The default is stdout.'),
    ] = None,
) -> None:
    """Truncate the mapped tables and load them from the graph."""
    try:
        result = asyncio.run(
            _run(
                source_url,
                target_url,
                graph=graph,
                tenant_slug=tenant_slug,
                tenant_name=tenant_name,
                allow_pending=allow_pending,
                dry_run=dry_run,
                output=output,
            )
        )
    except (mapping.EtlError, psycopg.Error) as error:
        typer.echo(f'ETL failed: {error}', err=True)
        raise typer.Exit(code=1) from error
    for name, table in result.tables.items():
        typer.echo(
            f'{name}: {table.rows} rows,'
            f' {sum(len(ids) for ids in table.skipped.values())} skipped,'
            f' {sum(table.changed.values())} changed',
            err=True,
        )
    if result.pending:
        typer.echo(
            f'{len(result.pending)} pending tables truncated and empty',
            err=True,
        )


async def _run(
    source_url: str,
    target_url: str,
    *,
    graph: str,
    tenant_slug: str,
    tenant_name: str,
    allow_pending: bool,
    dry_run: bool,
    output: pathlib.Path | None,
) -> runner.RunResult:
    async with (
        await psycopg.AsyncConnection.connect(source_url) as source,
        await psycopg.AsyncConnection.connect(target_url) as target,
    ):
        options: dict[str, typing.Any] = {
            'graph': graph,
            'tenant_slug': tenant_slug,
            'tenant_name': tenant_name,
            'allow_pending': allow_pending,
        }
        if not dry_run:
            return await runner.run(source, target, **options)
        if output is None:
            return await runner.run(
                source, target, dry_run=sys.stdout, **options
            )
        with output.open('w', encoding='utf-8') as stream:
            return await runner.run(source, target, dry_run=stream, **options)


@etl.command('reconcile')
def reconcile_command(
    source_url: SourceUrl,
    target_url: TargetUrl,
    output: typing.Annotated[
        pathlib.Path, typer.Option(help='Where to write the JSON report.')
    ],
    graph: Graph = 'imbi',
    tenant_slug: TenantSlug = 'default',
    tenant_name: TenantName = 'Default',
    table: typing.Annotated[
        list[str] | None,
        typer.Option(help='Check only this table. Repeat for more.'),
    ] = None,
) -> None:
    """Compare the loaded tables with the graph. Exit 1 on a mismatch."""
    try:
        report = asyncio.run(
            _reconcile(
                source_url,
                target_url,
                graph=graph,
                tenant_slug=tenant_slug,
                tenant_name=tenant_name,
                only=table,
            )
        )
    except (mapping.EtlError, psycopg.Error) as error:
        typer.echo(f'Reconciliation failed: {error}', err=True)
        raise typer.Exit(code=1) from error
    output.write_text(
        json.dumps(report.as_dict(), indent=2, sort_keys=True) + '\n',
        encoding='utf-8',
    )
    for name, result in report.tables.items():
        state = 'clean' if result.clean else '; '.join(result.mismatches)
        typer.echo(f'{name}: {state}', err=True)
    if not report.clean:
        raise typer.Exit(code=1)


async def _reconcile(
    source_url: str,
    target_url: str,
    *,
    graph: str,
    tenant_slug: str,
    tenant_name: str,
    only: list[str] | None,
) -> reconcile.Report:
    async with (
        await psycopg.AsyncConnection.connect(source_url) as source,
        await psycopg.AsyncConnection.connect(target_url) as target,
    ):
        return await reconcile.reconcile(
            source,
            target,
            graph=graph,
            tenant_slug=tenant_slug,
            tenant_name=tenant_name,
            only=only,
        )
