"""The order of the steps of a run (ADR 0021, Execution).

The engine and the test run share this walk. It reads the status and
the chosen port of each node, and returns the steps that can run and
the steps that cannot run any more.

- An edge is active when its source took the port of the edge, and
  inactive when its source is finished and took another port, or none.
- A step whose incoming edges are all inactive is ``skipped``.
- An ``any`` join is ready at its first active edge. An ``all`` join is
  ready when no edge waits and at least one edge is active.
"""

import typing

from imbi.common.workflows import graph

Status = typing.Literal[
    'pending', 'running', 'succeeded', 'failed', 'skipped', 'cancelled'
]

TERMINAL: frozenset[str] = frozenset(
    {'succeeded', 'failed', 'skipped', 'cancelled'}
)


def order(wf_graph: graph.Graph) -> list[str]:
    """Return the node ids in topological order.

    Ties keep the order of ``wf_graph.nodes``. Nodes on a cycle are not
    in the result; activation refuses a graph with a cycle.
    """
    pending = {n.id: 0 for n in wf_graph.nodes}
    for edge in wf_graph.edges:
        if edge.target in pending:
            pending[edge.target] += 1
    result = [n for n, count in pending.items() if count == 0]
    for node_id in result:
        for edge in wf_graph.edges:
            if edge.source == node_id and edge.target in pending:
                pending[edge.target] -= 1
                if pending[edge.target] == 0:
                    result.append(edge.target)
    return result


def _edge_state(
    edge: graph.Edge, status: dict[str, str], ports: dict[str, int | None]
) -> typing.Literal['active', 'inactive', 'waiting']:
    if status.get(edge.source) not in TERMINAL:
        return 'waiting'
    return 'active' if ports.get(edge.source) == edge.port else 'inactive'


def advance(
    wf_graph: graph.Graph,
    status: dict[str, str],
    ports: dict[str, int | None],
) -> tuple[list[str], list[str]]:
    """Return the ready steps and the steps that become ``skipped``.

    ``status`` is changed in place for the skipped steps. A pending node
    with no incoming edge is a trigger that did not start the run; the
    caller marks those ``skipped`` when the run starts.
    """
    nodes = order(wf_graph)
    parents: dict[str, list[graph.Edge]] = {n: [] for n in nodes}
    for edge in wf_graph.edges:
        if edge.target in parents:
            parents[edge.target].append(edge)
    joins = {n.id: n.join for n in wf_graph.nodes}
    skipped: list[str] = []
    ready: list[str] = []
    # Topological order: a skip reaches every step after it in one pass.
    for node_id in nodes:
        if status.get(node_id) != 'pending' or not parents[node_id]:
            continue
        states = [_edge_state(e, status, ports) for e in parents[node_id]]
        if all(s == 'inactive' for s in states):
            status[node_id] = 'skipped'
            skipped.append(node_id)
        elif 'active' in states and (
            joins[node_id] == 'any' or 'waiting' not in states
        ):
            ready.append(node_id)
    return ready, skipped
