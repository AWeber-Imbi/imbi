"""Baseline schema fields and log-type enrichment."""

_BASELINE: list[dict[str, object]] = [
    {'name': '@timestamp', 'label': 'Timestamp', 'type': 'date'},
    {'name': 'message', 'label': 'Message', 'type': 'text'},
    {'name': 'level', 'label': 'Level', 'type': 'keyword'},
    {'name': 'type', 'label': 'Log Type', 'type': 'keyword'},
    {'name': 'host', 'label': 'Host', 'type': 'keyword'},
    {'name': 'service', 'label': 'Service', 'type': 'keyword'},
    {'name': 'env', 'label': 'Environment', 'type': 'keyword'},
    {'name': 'tags', 'label': 'Tags', 'type': 'keyword'},
]


def build_schema(
    log_types: list[str] | None = None,
) -> list[dict[str, object]]:
    fields = [dict(f) for f in _BASELINE]
    if log_types:
        for field in fields:
            if field['name'] == 'type':
                field['choices'] = log_types
                break
    return fields
