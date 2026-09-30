"""``imbi-common etl audit``: the pre-migration audit (plan WP1.9).

The command only reads. It sets its transaction read only, so it can run
on production with a read-only login. It writes the JSON report to
``--output`` (or stdout), a summary to stderr, and exits 1 when a
blocking rule has rows or a rule fails.
"""

import asyncio
import json
import pathlib
import typing

import psycopg
import typer

from imbi.common.db.etl.audit import appendix_e, runner, sources


async def _audit(
    source_url: str,
    graph: str,
    only: list[str] | None,
    id_limit: int,
) -> runner.Report:
    async with await psycopg.AsyncConnection.connect(source_url) as conn:
        return await runner.run(
            conn,
            appendix_e.RULES,
            sources.SOURCES,
            graph=graph,
            only=only,
            id_limit=id_limit,
            not_covered=sources.NOT_COVERED,
            covered=appendix_e.COVERED,
        )


def audit_command(
    source_url: typing.Annotated[
        str,
        typer.Option(
            envvar='IMBI_ETL_SOURCE_URL',
            help='PostgreSQL URL of the database with the AGE graph.',
        ),
    ],
    output: typing.Annotated[
        pathlib.Path | None,
        typer.Option(help='Where to write the JSON report. Default: stdout.'),
    ] = None,
    graph: typing.Annotated[
        str, typer.Option(help='The AGE graph name (its schema).')
    ] = 'imbi',
    rule: typing.Annotated[
        list[str] | None,
        typer.Option(
            help='Run only the rules whose id starts with this value.'
            ' Repeat for more.'
        ),
    ] = None,
    id_limit: typing.Annotated[
        int, typer.Option(help='The most ids to report for each rule.')
    ] = runner.ID_LIMIT,
) -> None:
    """Count the graph rows that the relational schema rejects."""
    try:
        report = asyncio.run(_audit(source_url, graph, rule, id_limit))
    except psycopg.Error as error:
        typer.echo(f'Audit failed: {error}', err=True)
        raise typer.Exit(code=1) from error
    text = json.dumps(report.as_dict(), indent=2, sort_keys=True) + '\n'
    if output is None:
        typer.echo(text, nl=False)
    else:
        output.write_text(text, encoding='utf-8')
    for result in report.results:
        if result.error is not None:
            state = f'ERROR {result.error.splitlines()[0]}'
        elif not result.count:
            continue
        else:
            state = f'{result.count} ({result.rule.fate})'
        typer.echo(f'{result.rule.id}: {state}', err=True)
    if report.failed:
        raise typer.Exit(code=1)


def _group() -> None:
    """The pre-migration audit of the AGE graph."""


app = typer.Typer(no_args_is_help=True)
app.callback()(_group)
app.command('audit')(audit_command)
