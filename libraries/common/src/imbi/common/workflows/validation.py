"""Validation of a workflow version (ADR 0021).

Save stores a version with its issues. Activation needs a version with
no issues. A missing required parameter is a warning, so a draft can
have steps that are not configured yet; every other issue is an error.
"""

import itertools
import re
import typing

import jinja2
import jinja2.meta
import pydantic

from imbi.common.workflows import graph, registry

MAX_NODES = 100
MAX_EDGES = 200
#: The largest graph, in bytes of JSON.
MAX_GRAPH_BYTES = 64 * 1024

#: The scope name of the trigger payload in references.
TRIGGER_SCOPE = 'trigger'

#: Codes of the issues that make a graph too large to store.
LIMIT_CODES = frozenset(
    {'too_many_nodes', 'too_many_edges', 'graph_too_large'}
)

_CONCURRENCY_KEY = re.compile(r'^\{\{\s*trigger\.([a-z_][a-z0-9_]*)\s*\}\}$')

#: Only parses templates, to find the names they refer to.
_JINJA = jinja2.Environment(autoescape=False)  # noqa: S701

#: A branch that a run takes: (branching node id, port). A node with
#: no input is a branch ``('', node id)`` of a virtual root, because a
#: run starts from one trigger only.
type _Branch = tuple[str, str]


class _Issues(list[graph.ValidationIssue]):
    def add(
        self,
        severity: typing.Literal['error', 'warning'],
        code: str,
        message: str,
        *,
        node_id: str | None = None,
        edge_index: int | None = None,
    ) -> None:
        self.append(
            graph.ValidationIssue(
                severity=severity,
                code=code,
                message=message,
                node_id=node_id,
                edge_index=edge_index,
            )
        )


def _references(value: typing.Any) -> set[str]:
    """Return the root names that the templates in ``value`` use.

    Raises:
        jinja2.TemplateSyntaxError: A string is not a valid template.

    """
    if isinstance(value, str):
        if '{{' not in value and '{%' not in value:
            return set()
        return jinja2.meta.find_undeclared_variables(_JINJA.parse(value))
    if isinstance(value, list):
        items: list[typing.Any] = value
        return set().union(*(_references(v) for v in items))
    if isinstance(value, dict):
        mapping = typing.cast(dict[str, typing.Any], value)
        return set().union(*(_references(v) for v in mapping.values()))
    return set()


def _check_params(node: graph.Node, issues: _Issues) -> None:
    step = registry.STEP_TYPES[node.type]
    try:
        step.params.model_validate(node.params)
    except pydantic.ValidationError as e:
        for error in e.errors():
            where = '.'.join(str(p) for p in error['loc']) or 'params'
            if error['type'] == 'missing':
                issues.add(
                    'warning',
                    'missing_param',
                    f'{node.title}: {where} is required',
                    node_id=node.id,
                )
            else:
                issues.add(
                    'error',
                    'invalid_param',
                    f'{node.title}: {where}: {error["msg"]}',
                    node_id=node.id,
                )


def _check_concurrency(
    wf_graph: graph.Graph, settings: graph.Settings, issues: _Issues
) -> None:
    if settings.concurrency_mode != 'one_per_key':
        return
    if not settings.concurrency_key:
        issues.add(
            'warning',
            'missing_concurrency_key',
            'one_per_key needs a concurrency key',
        )
        return
    match = _CONCURRENCY_KEY.match(settings.concurrency_key)
    if match is None:
        issues.add(
            'error',
            'invalid_concurrency_key',
            'The concurrency key must be one reference to a trigger '
            'value, such as {{ trigger.service }}',
        )
        return
    name = match.group(1)
    for node in wf_graph.nodes:
        if node.type == 'schedule':
            issues.add(
                'error',
                'concurrency_key_with_schedule',
                'one_per_key cannot be used with a schedule trigger',
                node_id=node.id,
            )
        elif node.type == 'manual':
            raw: typing.Any = node.params.get('inputs')
            inputs: list[typing.Any] = raw if isinstance(raw, list) else []
            names = {
                typing.cast(dict[str, typing.Any], i).get('name')
                for i in inputs
                if isinstance(i, dict)
            }
            if name not in names:
                issues.add(
                    'error',
                    'concurrency_key_input_missing',
                    f'{node.title} must declare the input {name!r} that '
                    'the concurrency key uses',
                    node_id=node.id,
                )


def _by_node(branches: frozenset[_Branch]) -> dict[str, set[str]]:
    """Return the ports in ``branches``, by branching node."""
    index: dict[str, set[str]] = {}
    for node_id, port in branches:
        index.setdefault(node_id, set()).add(port)
    return index


def _exclusive(a: dict[str, set[str]], b: frozenset[_Branch]) -> bool:
    """Return whether two sets of required branches cannot both hold.

    ``a`` is one set indexed with :func:`_by_node`. Linear in ``b``.
    """
    return any(a.get(node_id, {port}) - {port} for node_id, port in b)


def validate(
    wf_graph: graph.Graph, settings: graph.Settings
) -> graph.ValidationResult:
    """Return the issues of a workflow version."""
    issues = _Issues()
    if len(wf_graph.nodes) > MAX_NODES:
        issues.add('error', 'too_many_nodes', f'More than {MAX_NODES} steps')
    if len(wf_graph.edges) > MAX_EDGES:
        issues.add(
            'error', 'too_many_edges', f'More than {MAX_EDGES} connections'
        )
    if len(wf_graph.model_dump_json().encode()) > MAX_GRAPH_BYTES:
        issues.add(
            'error',
            'graph_too_large',
            f'The graph is larger than {MAX_GRAPH_BYTES} bytes',
        )
    if not issues:
        _Validator(wf_graph, issues).run()
        _check_concurrency(wf_graph, settings, issues)
    return graph.ValidationResult(issues=issues)


class _Validator:
    """The structural checks of one graph."""

    def __init__(self, wf_graph: graph.Graph, issues: _Issues) -> None:
        self.graph = wf_graph
        self.issues = issues
        self.nodes: dict[str, graph.Node] = {}
        self.by_key: dict[str, str] = {}
        #: The number of output ports, by node id.
        self.ports: dict[str, int] = {}
        self.triggers: set[str] = set()
        #: Edge indexes into and out of each node.
        self.parents: dict[str, list[int]] = {}
        self.children: dict[str, list[int]] = {}

    def run(self) -> None:
        self._check_nodes()
        self._check_edges()
        order = self._check_cycles()
        self._check_reachability_and_references()
        if len(order) == len(self.nodes):
            self._check_any_joins(order)

    def _check_nodes(self) -> None:
        for node in self.graph.nodes:
            if node.id in self.nodes:
                self.issues.add(
                    'error',
                    'duplicate_node_id',
                    f'Two steps have the id {node.id!r}',
                    node_id=node.id,
                )
                continue
            self.nodes[node.id] = node
            self.parents[node.id] = []
            self.children[node.id] = []
            if node.key in self.by_key:
                self.issues.add(
                    'error',
                    'duplicate_key',
                    f'Two steps have the key {node.key!r}',
                    node_id=node.id,
                )
            self.by_key.setdefault(node.key, node.id)
            step = registry.STEP_TYPES.get(node.type)
            if step is None:
                self.issues.add(
                    'error',
                    'unknown_type',
                    f'{node.title}: unknown step type {node.type!r}',
                    node_id=node.id,
                )
                self.ports[node.id] = 1
                continue
            _check_params(node, self.issues)
            self.ports[node.id] = len(step.ports_for(node.params))
            if step.trigger:
                self.triggers.add(node.id)
        if not self.triggers:
            self.issues.add(
                'error', 'no_trigger', 'The workflow has no trigger'
            )

    def _check_edges(self) -> None:
        seen: set[tuple[str, int, str]] = set()
        for index, edge in enumerate(self.graph.edges):
            identity = (edge.source, edge.port, edge.target)
            if identity in seen:
                self.issues.add(
                    'error',
                    'duplicate_edge',
                    'The same connection is in the graph more than once',
                    edge_index=index,
                )
                continue
            seen.add(identity)
            if edge.source not in self.nodes or edge.target not in self.nodes:
                self.issues.add(
                    'error',
                    'unknown_node',
                    'The connection names a step that does not exist',
                    edge_index=index,
                )
                continue
            if edge.target in self.triggers:
                self.issues.add(
                    'error',
                    'edge_into_trigger',
                    f'{self.nodes[edge.target].title} is a trigger and '
                    'cannot have an input',
                    node_id=edge.target,
                    edge_index=index,
                )
            if edge.port >= self.ports[edge.source]:
                self.issues.add(
                    'error',
                    'port_out_of_range',
                    f'{self.nodes[edge.source].title} has no output '
                    f'{edge.port}',
                    node_id=edge.source,
                    edge_index=index,
                )
            self.parents[edge.target].append(index)
            self.children[edge.source].append(index)

    def _check_cycles(self) -> list[str]:
        """Return the nodes in topological order.

        Kahn's algorithm: the nodes that it cannot order are on a cycle,
        or after one.
        """
        pending = {n: len(self.parents[n]) for n in self.nodes}
        order = [n for n, count in pending.items() if count == 0]
        for node_id in order:
            for index in self.children[node_id]:
                target = self.graph.edges[index].target
                pending[target] -= 1
                if pending[target] == 0:
                    order.append(target)
        for node_id in self.nodes.keys() - set(order):
            self.issues.add(
                'error',
                'cycle',
                f'{self.nodes[node_id].title} is on or after a cycle',
                node_id=node_id,
            )
        return order

    def _ancestors(self, node_id: str) -> set[str]:
        seen: set[str] = set()
        stack = [node_id]
        while stack:
            for index in self.parents[stack.pop()]:
                source = self.graph.edges[index].source
                if source not in seen:
                    seen.add(source)
                    stack.append(source)
        return seen

    def _check_reachability_and_references(self) -> None:
        for node_id, node in self.nodes.items():
            ancestors = self._ancestors(node_id)
            if node_id not in self.triggers and not ancestors & self.triggers:
                self.issues.add(
                    'error',
                    'unreachable',
                    f'{node.title} cannot be reached from a trigger',
                    node_id=node_id,
                )
            try:
                names = _references(node.params)
            except jinja2.TemplateSyntaxError as e:
                self.issues.add(
                    'error',
                    'invalid_template',
                    f'{node.title}: {e.message}',
                    node_id=node_id,
                )
                continue
            for name in sorted(names - {TRIGGER_SCOPE}):
                if self.by_key.get(name) not in ancestors:
                    self.issues.add(
                        'error',
                        'unknown_reference',
                        f'{node.title}: {name!r} is not a step before '
                        'this one',
                        node_id=node_id,
                    )

    def _check_any_joins(self, order: list[str]) -> None:
        """Warn about ``any`` joins whose inputs can both arrive in a run.

        For each edge, this finds the branches that every path from a
        trigger to the edge takes. Two edges are exclusive when they
        need different ports of one branching node, or different
        triggers.

        ponytail: conservative. It does not see exclusion that holds
        only because of conditions inside a model prompt or the data,
        so it can warn about a join that never gets two inputs.
        """
        edge_branches: dict[int, frozenset[_Branch]] = {}
        for node_id in order:
            incoming = [edge_branches[i] for i in self.parents[node_id]]
            required: frozenset[_Branch] = (
                frozenset.intersection(*incoming)
                if incoming
                else frozenset({('', node_id)})
            )
            for index in self.children[node_id]:
                port = str(self.graph.edges[index].port)
                edge_branches[index] = (
                    required | {(node_id, port)}
                    if self.ports[node_id] > 1
                    else required
                )
            node = self.nodes[node_id]
            if node.join == 'any' and any(
                not _exclusive(a, b)
                for (a, _), (_, b) in itertools.combinations(
                    [(_by_node(i), i) for i in incoming], 2
                )
            ):
                self.issues.add(
                    'warning',
                    'any_join_overlap',
                    f'{node.title} can get more than one input in a run; '
                    'it runs on the first and ignores the rest',
                    node_id=node_id,
                )
