"""Run the write scenarios of ``scenarios/*.toml``.

A scenario is a list of steps. The runner puts the variables into each
step, sends it, saves the values that the step names, and records the
exchange. The key of an exchange is the scenario and the step, not the
path, because a created id is different on each side.

A step that does not return its ``expect`` status marks the scenario
as failed. The later steps are then recorded as not sent, except the
``always`` steps, which clean up.
"""

import dataclasses
import re
import time
import typing

from scripts.replay import client, models, pointer, templates

if typing.TYPE_CHECKING:
    import pathlib
    from collections import abc

_VARIABLE = re.compile(r'\{([A-Za-z_][A-Za-z0-9_]*)\}')

#: The status of a step that the runner did not send.
NOT_SENT = 0


class MissingVariable(KeyError):
    pass


def substitute(value: typing.Any, variables: dict[str, str]) -> typing.Any:
    """Replace ``{name}`` in every string of ``value``.

    A string that is only ``{name}`` keeps the type of the variable
    value, which is always a string here.
    """
    if isinstance(value, str):

        def replace(found: re.Match[str]) -> str:
            name = found.group(1)
            if name not in variables:
                raise MissingVariable(name)
            return variables[name]

        return _VARIABLE.sub(replace, value)
    if isinstance(value, dict):
        items = typing.cast('dict[str, typing.Any]', value)
        return {
            substitute(key, variables): substitute(item, variables)
            for key, item in items.items()
        }
    if isinstance(value, list):
        entries = typing.cast('list[typing.Any]', value)
        return [substitute(item, variables) for item in entries]
    return value


def select(body: typing.Any, path: str) -> typing.Any:
    """Return the value at the JSON pointer ``path``, or MISSING."""
    current = body
    for segment in pointer.parse(path):
        if isinstance(current, dict):
            items = typing.cast('dict[str, typing.Any]', current)
            if segment not in items:
                return pointer.MISSING
            current = items[segment]
        elif isinstance(current, list):
            entries = typing.cast('list[typing.Any]', current)
            if not segment.isdigit() or int(segment) >= len(entries):
                return pointer.MISSING
            current = entries[int(segment)]
        else:
            return pointer.MISSING
    return current


def _condition_met(
    wait_for: models.WaitFor, body: typing.Any, variables: dict[str, str]
) -> bool:
    value = select(body, wait_for.pointer)
    text = None if value is pointer.MISSING else str(value)
    if wait_for.equals is not None:
        return text == substitute(wait_for.equals, variables)
    return text != substitute(wait_for.not_equals, variables)


def load(directory: pathlib.Path) -> list[models.ScenarioFile]:
    """Read every scenario file of ``directory``, sorted by name."""
    return [
        models.load_toml(models.ScenarioFile, path)
        for path in sorted(directory.glob('*.toml'))
    ]


@dataclasses.dataclass
class Outcome:
    """The result of one scenario on one API."""

    domain: str
    name: str
    failures: list[str] = dataclasses.field(default_factory=list[str])


@dataclasses.dataclass
class Runner:
    client: client.Client
    routes: templates.RouteTable
    variables: dict[str, str]
    moves: list[models.Move] = dataclasses.field(
        default_factory=list[models.Move]
    )
    sleep: abc.Callable[[float], None] = time.sleep
    clock: abc.Callable[[], float] = time.monotonic

    def run(
        self, files: list[models.ScenarioFile]
    ) -> tuple[list[models.Exchange], list[Outcome]]:
        exchanges: list[models.Exchange] = []
        outcomes: list[Outcome] = []
        for scenario_file in files:
            for scenario in scenario_file.scenario:
                recorded, outcome = self._scenario(scenario_file, scenario)
                exchanges.extend(recorded)
                outcomes.append(outcome)
        return exchanges, outcomes

    def _scenario(
        self, scenario_file: models.ScenarioFile, scenario: models.Scenario
    ) -> tuple[list[models.Exchange], Outcome]:
        variables = dict(self.variables)
        outcome = Outcome(scenario_file.domain, scenario.name)
        exchanges: list[models.Exchange] = []
        for index, step in enumerate(scenario.step):
            key = (
                f'scenario:{scenario_file.domain}/{scenario.name}'
                f'#{index:02d} {step.method} {step.path}'
            )
            if step.name:
                key += f' ({step.name})'
            skip = bool(outcome.failures) and not step.always
            exchange = self._step(key, step, variables, skip=skip)
            exchanges.append(exchange)
            if exchange.status == NOT_SENT:
                if not skip:
                    outcome.failures.append(f'{key}: {exchange.error}')
                continue
            if exchange.error is not None:
                outcome.failures.append(f'{key}: {exchange.error}')
            wanted = step.expected_statuses
            if wanted and exchange.status not in wanted:
                outcome.failures.append(
                    f'{key}: status {exchange.status}, expected {wanted}'
                )
            for name, path in step.save.items():
                value = select(exchange.body, path)
                if value is pointer.MISSING or value is None:
                    outcome.failures.append(
                        f'{key}: the response has no value at {path}'
                    )
                else:
                    variables[name] = str(value)
        return exchanges, outcome

    def _step(
        self,
        key: str,
        step: models.Step,
        variables: dict[str, str],
        *,
        skip: bool,
    ) -> models.Exchange:
        route = f'{step.method} {step.path}'
        try:
            path = substitute(step.path, variables)
            query = typing.cast(
                'dict[str, str]', substitute(step.query, variables)
            )
            body = substitute(step.body, variables)
        except MissingVariable as error:
            return self._not_sent(
                key, route, step, f'no value for variable {error}'
            )
        route = self.routes.resolve(step.method, path) or route
        if skip:
            return self._not_sent(
                key, route, step, 'not sent: an earlier step failed'
            )
        target = templates.move(self.moves, step.method, path, variables)
        deadline = self.clock() + (
            step.wait_for.timeout if step.wait_for else 0.0
        )
        while True:
            exchange = client.capture(
                self.client,
                key=key,
                kind='scenario',
                route=route,
                method=step.method,
                path=target,
                query=query,
                body=body,
                normalize=step.normalize,
            )
            if step.wait_for is None:
                return exchange
            if _condition_met(step.wait_for, exchange.body, variables):
                return exchange
            if self.clock() >= deadline:
                exchange.error = (
                    f'wait_for {step.wait_for.pointer}: the value was not '
                    f'correct after {step.wait_for.timeout} seconds'
                )
                return exchange
            self.sleep(step.wait_for.interval)

    @staticmethod
    def _not_sent(
        key: str, route: str, step: models.Step, reason: str
    ) -> models.Exchange:
        return models.Exchange(
            key=key,
            kind='scenario',
            route=route,
            method=step.method,
            path=step.path,
            status=NOT_SENT,
            error=reason,
            normalize=list(step.normalize),
        )
