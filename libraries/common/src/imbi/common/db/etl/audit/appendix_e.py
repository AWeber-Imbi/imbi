"""The rules of plan Appendix E, one query each (or one per part).

Each query uses the placeholder dialect of ``rules.py`` and returns one
text column, ``id``. The schema rules of ``checks.py`` also count E3
(duplicate slugs), E4 (slug formats), and parts of E30 (JSON text); the
rules here are the ones that the schema cannot show.

The property names come from the code that writes each label (plan
WP1.9 research, 2026-09-30).
"""

# The queries are constants of this module. They take no input: the
# graph name goes in with sql.Identifier (rules.expand).
# ruff: noqa: S608

from imbi.common.db.etl.audit import rules, sources

_ORG = sources.PROJECT_ORG

#: The graph id of a vertex ``v`` when it has no ``id`` property.
_ID = "coalesce(v.p->>'id', 'gid:' || v.gid::text)"


def _rule(
    rule_id: str,
    title: str,
    fate: rules.Fate,
    query: str,
    acts_on: str,
    decision: str | None = None,
    requires: tuple[str, ...] = (),
) -> rules.Rule:
    return rules.Rule(
        id=rule_id,
        title=title,
        fate=fate,
        query=query,
        acts_on=acts_on,
        decision=decision,
        requires=requires,
    )


_EMBEDDED_LABELS = (
    'AIModel',
    'AIProvider',
    'Blueprint',
    'Comment',
    'ComponentNote',
    'Document',
    'DocumentTemplate',
    'Environment',
    'Integration',
    'LinkDefinition',
    'MCPServer',
    'Organization',
    'Project',
    'ProjectType',
    'Release',
    'Tag',
    'Team',
)

_EMBEDDING_ID = (
    "e.node_label || '/' || e.node_id || '/' || e.attribute || '/'"
    " || e.chunk_index::text || '/' || e.model_name"
)

_JSON_TEXT = (
    "SELECT 'Blueprint.' || k || '/' || (v.p->>'id') AS id"
    " FROM {Blueprint} v CROSS JOIN unnest(ARRAY['filter',"
    " 'json_schema']) k WHERE jsonb_typeof(v.p->k) = 'string'"
    " UNION ALL SELECT 'ScoringPolicy.' || k || '/' || (v.p->>'id')"
    " FROM {ScoringPolicy} v CROSS JOIN unnest(ARRAY['value_score_map',"
    " 'range_score_map', 'age_score_map', 'status_score_map',"
    " 'condition']) k WHERE jsonb_typeof(v.p->k) = 'string'"
    " UNION ALL SELECT 'WebhookRule.handler_config/'"
    " || coalesce(w.p->>'id', '?') || '/' || coalesce(r.p->>'ordinal', '?')"
    ' FROM {WebhookRule} r LEFT JOIN ({ACTIONS} a JOIN {Webhook} w'
    ' ON w.gid = a.t) ON a.s = r.gid WHERE jsonb_typeof('
    "r.p->'handler_config') = 'string'"
    " UNION ALL SELECT 'USES.' || k || '/' || coalesce(pr.p->>'id',"
    " pt.p->>'id', '?') || '/' || coalesce(i.p->>'id', '?') || '/'"
    " || coalesce(u.p->>'capability', '') FROM {USES} u"
    ' LEFT JOIN {Project} pr ON pr.gid = u.s'
    ' LEFT JOIN {ProjectType} pt ON pt.gid = u.s'
    ' LEFT JOIN {Integration} i ON i.gid = u.t'
    " CROSS JOIN unnest(ARRAY['options', 'env_payloads']) k"
    " WHERE jsonb_typeof(u.p->k) = 'string'"
    " UNION ALL SELECT 'Message.' || k || '/' || (v.p->>'id')"
    " FROM {Message} v CROSS JOIN unnest(ARRAY['tool_use', 'tool_results',"
    " 'token_usage']) k WHERE jsonb_typeof(v.p->k) = 'string'"
    " UNION ALL SELECT 'MCPServer.ignored_tools/' || (v.p->>'id')"
    " FROM {MCPServer} v WHERE jsonb_typeof(v.p->'ignored_tools') = 'string'"
    " UNION ALL SELECT 'AwsAccount.tags/' || (v.p->>'id') FROM {AwsAccount} v"
    " WHERE jsonb_typeof(v.p->'tags') = 'string'"
    " UNION ALL SELECT 'MAPS_TO.tags/' || coalesce(env.p->>'id', '?') || '/'"
    " || coalesce(ac.p->>'id', '?') FROM {MAPS_TO} m"
    ' LEFT JOIN {Environment} env ON env.gid = m.s'
    ' LEFT JOIN {AwsAccount} ac ON ac.gid = m.t'
    " WHERE jsonb_typeof(m.p->'tags') = 'string'"
    " UNION ALL SELECT 'Release.links/' || (v.p->>'id') FROM {Release} v"
    " WHERE jsonb_typeof(v.p->'links') = 'string'"
    " UNION ALL SELECT 'ComponentRelease.hashes/' || (v.p->>'id')"
    " FROM {ComponentRelease} v WHERE jsonb_typeof(v.p->'hashes') = 'string'"
    " UNION ALL SELECT 'Comment.' || k || '/' || (v.p->>'id')"
    " FROM {Comment} v CROSS JOIN unnest(ARRAY['mentions',"
    " 'acknowledged_by']) k WHERE jsonb_typeof(v.p->k) = 'string'"
    " UNION ALL SELECT 'DocumentTemplate.project_type_slugs/'"
    " || (v.p->>'id') FROM {DocumentTemplate} v"
    " WHERE jsonb_typeof(v.p->'project_type_slugs') = 'string'"
    " UNION ALL SELECT k || '/' || (v.p->>'id') FROM {APIKey} v"
    " CROSS JOIN unnest(ARRAY['scopes']) k"
    " WHERE jsonb_typeof(v.p->k) = 'string'"
    " UNION ALL SELECT k || '/' || (v.p->>'id') FROM {ClientCredential} v"
    " CROSS JOIN unnest(ARRAY['scopes']) k"
    " WHERE jsonb_typeof(v.p->k) = 'string'"
    " UNION ALL SELECT k || '/' || (v.p->>'id') FROM {IdentityConnection} v"
    " CROSS JOIN unnest(ARRAY['scopes']) k"
    " WHERE jsonb_typeof(v.p->k) = 'string'"
)

_EMPTY_TEXT = (
    "SELECT 'AnalysisResult.remediation/' || coalesce(v.p->>'report_id', '?')"
    " || '/' || coalesce(v.p->>'plugin_id', '') || '/'"
    " || coalesce(v.p->>'slug', '') AS id FROM {AnalysisResult} v"
    " WHERE v.p->'remediation' = to_jsonb(''::text)"
    " UNION ALL SELECT 'AnalysisReport.triggered_by/' || (v.p->>'id')"
    ' FROM {AnalysisReport} v'
    " WHERE v.p->'triggered_by_user_id' = to_jsonb(''::text)"
    " UNION ALL SELECT 'Project.' || k || '/' || (v.p->>'id')"
    " FROM {Project} v CROSS JOIN unnest(ARRAY['promote_environment',"
    " 'promote_from_environment']) k WHERE v.p->k = to_jsonb(''::text)"
)

#: E38: JSON text that E30 does not list.
_JSON_TEXT_ADDED = (
    "SELECT 'Project.' || k || '/' || (v.p->>'id') AS id FROM {Project} v"
    " CROSS JOIN unnest(ARRAY['links', 'identifiers']) k"
    " WHERE jsonb_typeof(v.p->k) = 'string'"
    " UNION ALL SELECT 'Integration.' || k || '/' || (v.p->>'id')"
    " FROM {Integration} v CROSS JOIN unnest(ARRAY['options',"
    " 'encrypted_credentials', 'capabilities', 'links', 'identifiers']) k"
    " WHERE jsonb_typeof(v.p->k) = 'string'"
    " UNION ALL SELECT 'IdentityConnection.metadata/' || (v.p->>'id')"
    ' FROM {IdentityConnection} v'
    " WHERE jsonb_typeof(v.p->'metadata') = 'string'"
)

#: E38: numbers that the graph keeps as text (a Decimal as a string).
_NUMERIC_TEXT = (
    "SELECT 'AIModel.' || k || '/' || (v.p->>'id') AS id FROM {AIModel} v"
    " CROSS JOIN unnest(ARRAY['input_cost_per_million',"
    " 'output_cost_per_million', 'monthly_spend_cap']) k"
    " WHERE jsonb_typeof(v.p->k) = 'string'"
)

#: E38: the '' values of the set_status() writers of the sync and
#: promotion state.
_EMPTY_TEXT_ADDED = (
    "SELECT 'Project.' || k || '/' || (v.p->>'id') AS id FROM {Project} v"
    " CROSS JOIN unnest(ARRAY['commit_sync_by', 'commit_sync_error',"
    " 'deployment_sync_by', 'deployment_sync_error', 'pr_sync_by',"
    " 'pr_sync_error', 'promote_by', 'promote_error', 'promote_tag',"
    " 'promote_committish', 'promote_run_id', 'promote_run_url']) k"
    " WHERE v.p->k = to_jsonb(''::text)"
)

#: The labels whose ids E36 derives.
_NO_ID_LABELS = (
    'Organization',
    'Role',
    'User',
    'WebhookRule',
    'AnalysisResult',
    'PluginRegistration',
)

#: E39: the labels whose API writes by slug, so it cannot split E3
#: duplicates. Each has a BELONGS_TO edge to its organization.
_SLUG_WRITE_LABELS = ('Environment', 'ProjectType', 'Tag', 'DocumentTemplate')

RULES: list[rules.Rule] = [
    _rule(
        'E1',
        'More than one Organization',
        'blocking',
        f'SELECT {_ID} AS id FROM {{Organization}} v'
        ' WHERE (SELECT count(*) FROM {Organization}) > 1',
        'WP1.9',
        decision='O2',
    ),
    _rule(
        'E2',
        'The tenant: the ETL creates one tenants row',
        'changed',
        "SELECT 'tenant' AS id",
        'WP1.5',
    ),
    _rule(
        'E5',
        'Users whose email differs from another user email only in case',
        'blocking',
        f'SELECT {_ID} AS id FROM {{User}} v'
        " WHERE lower(v.p->>'email') IN (SELECT lower(u.p->>'email')"
        " FROM {User} u GROUP BY lower(u.p->>'email')"
        ' HAVING count(*) > 1)',
        'WP2.1',
        decision='O3',
    ),
    _rule(
        'E5.not_lower',
        'User emails that are not in lower case (O3: store lower case)',
        'changed',
        f'SELECT {_ID} AS id FROM {{User}} v'
        " WHERE v.p->>'email' <> lower(v.p->>'email')",
        'WP2.1',
        decision='O3',
    ),
    _rule(
        'E6',
        'Users with is_service_account',
        'blocking',
        f'SELECT {_ID} AS id FROM {{User}} v'
        " WHERE v.p->'is_service_account' = 'true'::jsonb",
        'WP2.1',
        decision='O6',
    ),
    _rule(
        'E7',
        'MEMBER_OF to an Organization with no role, or with a role slug'
        ' that no Role has; the ETL gives the readonly role',
        'changed',
        "SELECT coalesce(v.p->>'id', 'gid:' || v.gid::text) || '/'"
        " || coalesce(o.p->>'id', 'gid:' || o.gid::text) AS id"
        ' FROM {MEMBER_OF} m JOIN {Organization} o ON o.gid = m.t'
        ' JOIN (SELECT gid, p FROM {User} UNION ALL'
        ' SELECT gid, p FROM {ServiceAccount}) v ON v.gid = m.s'
        " WHERE nullif(m.p->'role', 'null'::jsonb) IS NULL OR NOT EXISTS"
        " (SELECT 1 FROM {Role} r WHERE r.p->>'slug' = m.p->>'role')",
        'WP2.1',
    ),
    _rule(
        'E8',
        'Projects with no OWNED_BY team',
        'blocking',
        f'SELECT {_ID} AS id FROM {{Project}} v WHERE NOT EXISTS'
        ' (SELECT 1 FROM {OWNED_BY} ob JOIN {Team} t ON t.gid = ob.t'
        ' WHERE ob.s = v.gid)',
        'WP3.0, WP2.2',
    ),
    _rule(
        'E9.TYPE',
        'Duplicate TYPE edges for one (project, project type)',
        'changed',
        "SELECT (s.p->>'id') || '/' || (t.p->>'id') AS id FROM {TYPE} e"
        ' JOIN {Project} s ON s.gid = e.s JOIN {ProjectType} t ON t.gid = e.t'
        " GROUP BY s.p->>'id', t.p->>'id' HAVING count(*) > 1",
        'WP2.2',
    ),
    _rule(
        'E9.DEPLOYED_IN',
        'Duplicate DEPLOYED_IN edges for one (project, environment)',
        'changed',
        "SELECT (s.p->>'id') || '/' || (t.p->>'id') AS id"
        ' FROM {DEPLOYED_IN} e JOIN {Project} s ON s.gid = e.s'
        ' JOIN {Environment} t ON t.gid = e.t'
        " GROUP BY s.p->>'id', t.p->>'id' HAVING count(*) > 1",
        'WP2.4',
    ),
    _rule(
        'E9.EXISTS_IN',
        'Duplicate EXISTS_IN edges for one (project, integration)',
        'changed',
        "SELECT (s.p->>'id') || '/' || (t.p->>'id') AS id"
        ' FROM {EXISTS_IN} e JOIN {Project} s ON s.gid = e.s'
        ' JOIN {Integration} t ON t.gid = e.t'
        " GROUP BY s.p->>'id', t.p->>'id' HAVING count(*) > 1",
        'WP2.7',
    ),
    _rule(
        'E10.Project',
        'Projects whose archived flag disagrees with archived_at',
        'changed',
        f'SELECT {_ID} AS id FROM {{Project}} v'
        " WHERE coalesce(v.p->'archived' = 'true'::jsonb, false)"
        " <> (nullif(v.p->'archived_at', 'null'::jsonb) IS NOT NULL)",
        'WP2.2',
    ),
    _rule(
        'E10.CommentThread',
        'Comment threads whose resolved flag disagrees with resolved_at',
        'changed',
        f'SELECT {_ID} AS id FROM {{CommentThread}} v'
        " WHERE coalesce(v.p->'resolved' = 'true'::jsonb, false)"
        " <> (nullif(v.p->'resolved_at', 'null'::jsonb) IS NOT NULL)",
        'WP2.6',
    ),
    *(
        _rule(
            f'E10.{label}',
            f'{label} nodes whose revoked flag disagrees with revoked_at',
            'changed',
            f'SELECT {_ID} AS id FROM {{{label}}} v'
            " WHERE coalesce(v.p->'revoked' = 'true'::jsonb, false)"
            " <> (nullif(v.p->'revoked_at', 'null'::jsonb) IS NOT NULL)",
            'WP2.3',
        )
        for label in ('APIKey', 'ClientCredential', 'TokenMetadata')
    ),
    _rule(
        'E11',
        'IdentityConnections that share (integration_id, subject)',
        'blocking',
        "SELECT id FROM (SELECT coalesce(v.p->>'id', 'gid:' || v.gid::text)"
        ' AS id, count(*) OVER (PARTITION BY'
        " v.p->>'integration_id', v.p->>'subject') AS n"
        " FROM {IdentityConnection} v WHERE v.p->>'subject' IS NOT NULL)"
        ' x WHERE n > 1',
        'WP2.3',
        decision='O4',
    ),
    _rule(
        'E12',
        'IdentityConnections whose integration_id names no Integration',
        'skipped',
        f'SELECT {_ID} AS id FROM {{IdentityConnection}} v'
        ' WHERE NOT EXISTS (SELECT 1 FROM {Integration} i'
        " WHERE i.p->'id' = v.p->'integration_id')",
        'WP2.3',
    ),
    _rule(
        'E13',
        'OAuthIdentity nodes',
        'blocking',
        f'SELECT {_ID} AS id FROM {{OAuthIdentity}} v',
        'WP2.3',
        decision='O5',
    ),
    _rule(
        'E14.tag',
        'Releases that share (project, tag)',
        'blocking',
        "SELECT id FROM (SELECT r.p->>'id' AS id, count(*) OVER"
        " (PARTITION BY v.p->>'id', r.p->>'tag') AS n FROM {HAS_RELEASE} h"
        ' JOIN {Project} v ON v.gid = h.s JOIN {Release} r ON r.gid = h.t'
        " WHERE NULLIF(r.p->>'tag', '') IS NOT NULL) x WHERE n > 1",
        'WP2.4',
    ),
    _rule(
        'E14.commit',
        'Untagged Releases that share (project, committish)',
        'blocking',
        "SELECT id FROM (SELECT r.p->>'id' AS id, count(*) OVER"
        " (PARTITION BY v.p->>'id', r.p->>'committish') AS n"
        ' FROM {HAS_RELEASE} h JOIN {Project} v ON v.gid = h.s'
        ' JOIN {Release} r ON r.gid = h.t'
        " WHERE NULLIF(r.p->>'tag', '') IS NULL) x WHERE n > 1",
        'WP2.4',
    ),
    _rule(
        'E15.Release',
        'Releases that no Project owns',
        'skipped',
        f'SELECT {_ID} AS id FROM {{Release}} v WHERE NOT EXISTS'
        ' (SELECT 1 FROM {HAS_RELEASE} h JOIN {Project} p ON p.gid = h.s'
        ' WHERE h.t = v.gid)',
        'WP2.4',
        decision='O10',
    ),
    _rule(
        'E15.Release.DEPLOYED_TO',
        'Releases that no Project owns and that keep a DEPLOYED_TO array'
        ' (the #277 set)',
        'skipped',
        f'SELECT DISTINCT {_ID} AS id FROM {{Release}} v'
        ' JOIN {DEPLOYED_TO} dt ON dt.s = v.gid'
        " WHERE dt.p->'deployments' IS NOT NULL AND NOT EXISTS"
        ' (SELECT 1 FROM {HAS_RELEASE} h JOIN {Project} p ON p.gid = h.s'
        ' WHERE h.t = v.gid)',
        'WP2.4',
        decision='O10',
    ),
    _rule(
        'E15.Deployment',
        'Deployments with no BELONGS_TO Project',
        'skipped',
        f'SELECT {_ID} AS id FROM {{Deployment}} v WHERE NOT EXISTS'
        ' (SELECT 1 FROM {BELONGS_TO} b JOIN {Project} p ON p.gid = b.t'
        ' WHERE b.s = v.gid)',
        'WP2.4',
    ),
    _rule(
        'E15.Blocker',
        'Blockers with no Release, or whose Release has no Project',
        'skipped',
        f'SELECT {_ID} AS id FROM {{Blocker}} v WHERE NOT EXISTS'
        ' (SELECT 1 FROM {BLOCKED_BY} e JOIN {Release} r ON r.gid = e.s'
        ' JOIN {HAS_RELEASE} h ON h.t = r.gid'
        ' JOIN {Project} p ON p.gid = h.s WHERE e.t = v.gid)',
        'WP2.4',
    ),
    _rule(
        'E16',
        'Deployments with no TARGETS environment',
        'skipped',
        f'SELECT {_ID} AS id FROM {{Deployment}} v WHERE NOT EXISTS'
        ' (SELECT 1 FROM {TARGETS} t JOIN {Environment} e ON e.gid = t.t'
        ' WHERE t.s = v.gid)',
        'WP2.4',
    ),
    _rule(
        'E17',
        'DEPLOYED_IN.current_release that names no Release',
        'changed',
        "SELECT (v.p->>'id') || '/' || (e.p->>'id') AS id"
        ' FROM {DEPLOYED_IN} di JOIN {Project} v ON v.gid = di.s'
        ' JOIN {Environment} e ON e.gid = di.t'
        " WHERE nullif(di.p->'current_release', 'null'::jsonb) IS NOT NULL"
        ' AND NOT EXISTS (SELECT 1 FROM {Release} r'
        " WHERE r.p->'id' = di.p->'current_release')",
        'WP2.4',
    ),
    _rule(
        'E18',
        'DEPLOYED_IN keys that are not current_* and that no enabled'
        ' relationship blueprint declares',
        'changed',
        'WITH '
        + sources.BLUEPRINT_ENV_KEYS
        + " SELECT (v.p->>'id') || '/' || (e.p->>'id') || ':' || k.key AS id"
        ' FROM {DEPLOYED_IN} di JOIN {Project} v ON v.gid = di.s'
        ' JOIN {Environment} e ON e.gid = di.t'
        ' CROSS JOIN LATERAL jsonb_object_keys(di.p) AS k(key)'
        " WHERE k.key NOT IN ('current_release', 'current_release_at',"
        " 'current_deployment_external_id', 'current_state_source',"
        " 'current_state_observed_at')"
        ' AND k.key NOT IN (SELECT key FROM bp_keys)',
        'WP2.4',
    ),
    _rule(
        'E19',
        'Project promote_* environment slugs that name no environment of'
        ' the organization',
        'changed',
        'WITH ' + _ORG + ", env AS (SELECT e.p, o.p->'id' AS org_id"
        ' FROM {Environment} e JOIN {BELONGS_TO} b ON b.s = e.gid'
        ' JOIN {Organization} o ON o.gid = b.t)'
        " SELECT (v.p->>'id') || '/' || k.key AS id FROM {Project} v"
        ' LEFT JOIN own ON own.project_gid = v.gid'
        " CROSS JOIN LATERAL (VALUES ('promote_environment'),"
        " ('promote_from_environment')) AS k(key)"
        " WHERE NULLIF(v.p->>k.key, '') IS NOT NULL AND NOT EXISTS"
        ' (SELECT 1 FROM env x WHERE x.org_id = own.organization_id'
        " AND x.p->>'slug' = v.p->>k.key)",
        'WP2.4',
    ),
    _rule(
        'E20',
        'More than one open blocker for one (release, external_ref)',
        'blocking',
        "SELECT id FROM (SELECT b.p->>'id' AS id, count(*) OVER"
        " (PARTITION BY r.p->>'id', b.p->>'external_ref') AS n"
        ' FROM {Blocker} b JOIN {BLOCKED_BY} e ON e.t = b.gid'
        " JOIN {Release} r ON r.gid = e.s WHERE b.p->>'status' = 'open'"
        " AND b.p->>'external_ref' IS NOT NULL) x WHERE n > 1",
        'WP3.0, WP2.4',
    ),
    _rule(
        'E21',
        'Component identifiers that more than one Component claims',
        'changed',
        f'SELECT {_ID} AS id FROM {{ComponentIdentifier}} v'
        ' JOIN {IDENTIFIED_BY} e ON e.t = v.gid'
        ' GROUP BY v.gid, v.p HAVING count(DISTINCT e.s) > 1',
        'WP2.5',
    ),
    _rule(
        'E22',
        'DocumentTemplate nodes: the ETL gives each one a new id',
        'changed',
        f'SELECT {_ID} AS id FROM {{DocumentTemplate}} v',
        'WP2.6',
    ),
    _rule(
        'E23',
        'Templates whose project_type_slugs name no live project type of'
        ' the organization',
        'blocking',
        f'SELECT {_ID} AS id FROM {{DocumentTemplate}} v'
        ' LEFT JOIN LATERAL (SELECT o.gid FROM {BELONGS_TO} b'
        ' JOIN {Organization} o ON o.gid = b.t WHERE b.s = v.gid'
        " ORDER BY o.p->>'id' LIMIT 1) org ON true"
        " WHERE jsonb_typeof(v.p->'project_type_slugs') = 'array'"
        ' AND EXISTS (SELECT 1 FROM jsonb_array_elements_text('
        "v.p->'project_type_slugs') AS s(slug) WHERE NOT EXISTS"
        ' (SELECT 1 FROM {ProjectType} pt JOIN {BELONGS_TO} pb'
        " ON pb.s = pt.gid WHERE pb.t = org.gid AND pt.p->>'slug' = s.slug))",
        'WP3.0, WP2.6',
    ),
    _rule(
        'E24',
        'Integration.plugin values with no PluginRegistration',
        'changed',
        f'SELECT {_ID} AS id FROM {{Integration}} v WHERE NOT EXISTS'
        ' (SELECT 1 FROM {PluginRegistration} r'
        " WHERE r.p->>'slug' = v.p->>'plugin')",
        'WP2.7',
    ),
    _rule(
        'E24.slug',
        'Integration.plugin values that the slug domain rejects',
        'blocking',
        f'SELECT {_ID} AS id FROM {{Integration}} v'
        " WHERE NOT coalesce(v.p->>'plugin', '') ~ '^[a-z0-9]+(-[a-z0-9]+)*$'",
        'WP2.7',
    ),
    _rule(
        'E25',
        'Organization integrations with used_as_login',
        'blocking',
        f'SELECT {_ID} AS id FROM {{Integration}} v'
        ' JOIN {BELONGS_TO} bo ON bo.s = v.gid'
        ' JOIN {Organization} o ON o.gid = bo.t'
        " WHERE v.p->'used_as_login' = 'true'::jsonb",
        'WP3.0, WP2.7',
    ),
    _rule(
        'E26',
        'Webhook rule handlers that do not match'
        ' ^[a-z][a-z0-9-]*#[a-z][a-z0-9_]*$',
        'blocking',
        "SELECT coalesce(w.p->>'id', '?') || '/'"
        " || coalesce(r.p->>'ordinal', '?') AS id FROM {WebhookRule} r"
        ' LEFT JOIN ({ACTIONS} a JOIN {Webhook} w ON w.gid = a.t)'
        " ON a.s = r.gid WHERE jsonb_typeof(r.p->'handler')"
        " IS DISTINCT FROM 'string'"
        " OR NOT (r.p->>'handler' ~ '^[a-z][a-z0-9-]*#[a-z][a-z0-9_]*$')",
        'WP3.0, WP2.7',
    ),
    _rule(
        'E27',
        'Webhook identity pin slugs that do not resolve in the organization'
        ' or to the instance sign-in provider',
        'changed',
        f'SELECT {_ID} AS id FROM {{Webhook}} v'
        ' JOIN {IMPLEMENTED_BY} ib ON ib.s = v.gid'
        ' LEFT JOIN ({BELONGS_TO} bo JOIN {Organization} o ON o.gid = bo.t)'
        " ON bo.s = v.gid WHERE coalesce(ib.p->>'identity_integration_slug',"
        " '') <> '' AND NOT EXISTS (SELECT 1 FROM {Integration} i"
        ' LEFT JOIN {BELONGS_TO} ib2 ON ib2.s = i.gid'
        " WHERE i.p->>'slug' = ib.p->>'identity_integration_slug'"
        ' AND (ib2.t = o.gid OR ib2.s IS NULL))',
        'WP2.7',
    ),
    _rule(
        'E28',
        'Embedding rows of the text model without 384 dimensions',
        'blocking',
        f'SELECT {_EMBEDDING_ID} AS id FROM public.embeddings e'
        " WHERE e.model_name = 'text' AND vector_dims(e.embedding) <> 384",
        'WP2.10',
        requires=('public.embeddings',),
    ),
    _rule(
        'E29',
        'Embedding rows whose entity is not in the graph',
        'skipped',
        'WITH ent(label, id) AS ('
        + ' UNION ALL '.join(
            f"SELECT '{label}', v.p->>'id' FROM {{{label}}} v"
            for label in _EMBEDDED_LABELS
        )
        + f') SELECT {_EMBEDDING_ID} AS id FROM public.embeddings e'
        " WHERE e.node_label NOT IN ('Component', 'Role') AND NOT EXISTS"
        ' (SELECT 1 FROM ent x WHERE x.label = e.node_label'
        ' AND x.id = e.node_id)',
        'WP2.10',
        requires=('public.embeddings',),
    ),
    _rule(
        'E30',
        'Properties that hold JSON text; the ETL decodes them',
        'changed',
        _JSON_TEXT,
        'each WP of the label',
    ),
    _rule(
        'E30.empty',
        "Properties that hold ''; the ETL writes NULL",
        'changed',
        _EMPTY_TEXT,
        'each WP of the label',
    ),
    _rule(
        'E36',
        'Nodes with no id property: the ETL derives the id from the graph id',
        'changed',
        ' UNION ALL '.join(
            f"SELECT '{label}/' || v.gid::text AS id FROM {{{label}}} v"
            f" WHERE v.p->>'id' LIKE '{rules.DERIVED_ID_PREFIX}%'"
            for label in _NO_ID_LABELS
        ),
        'WP2.1, WP2.3, WP2.7, WP2.8',
    ),
    _rule(
        'E37.Document',
        'Documents with no ATTACHED_TO target: the one organization, no'
        ' target',
        'changed',
        f'SELECT {_ID} AS id FROM {{Document}} v WHERE NOT EXISTS'
        ' (SELECT 1 FROM {ATTACHED_TO} a WHERE a.s = v.gid AND ('
        'EXISTS (SELECT 1 FROM {Project} x WHERE x.gid = a.t)'
        ' OR EXISTS (SELECT 1 FROM {ProjectType} x WHERE x.gid = a.t)'
        ' OR EXISTS (SELECT 1 FROM {User} x WHERE x.gid = a.t)))',
        'WP2.6',
    ),
    _rule(
        'E37.CommentThread',
        'Comment threads with no document: skipped, with their comments',
        'skipped',
        f'SELECT {_ID} AS id FROM {{CommentThread}} v WHERE NOT EXISTS'
        ' (SELECT 1 FROM {ON_DOCUMENT} e JOIN {Document} d ON d.gid = e.t'
        ' WHERE e.s = v.gid)',
        'WP2.6',
    ),
    _rule(
        'E38.json_text',
        'JSON text that E30 does not list: Project links and identifiers,'
        ' five Integration maps, IdentityConnection.metadata',
        'changed',
        _JSON_TEXT_ADDED,
        'WP2.2, WP2.3, WP2.7',
    ),
    _rule(
        'E38.numeric_text',
        'AIModel cost and spend cap values that the graph keeps as text',
        'changed',
        _NUMERIC_TEXT,
        'WP2.8',
    ),
    _rule(
        'E38.empty',
        "'' values of the sync and promotion state; the ETL writes NULL",
        'changed',
        _EMPTY_TEXT_ADDED,
        'WP2.2',
    ),
    _rule(
        'E38.release_tag',
        "Releases whose tag is ''",
        'blocking',
        f'SELECT {_ID} AS id FROM {{Release}} v'
        " WHERE v.p->'tag' = to_jsonb(''::text)",
        'WP3.0, WP2.4',
    ),
    _rule(
        'E39',
        'Duplicate slugs in one organization that the API cannot split'
        ' (environments, project types, tags, templates)',
        'blocking',
        ' UNION ALL '.join(
            'SELECT id FROM (SELECT'
            f" '{label}/' || coalesce(v.p->>'id', v.gid::text) AS id,"
            " count(*) OVER (PARTITION BY o.gid, v.p->>'slug') AS n"
            f' FROM {{{label}}} v JOIN {{BELONGS_TO}} b ON b.s = v.gid'
            ' JOIN {Organization} o ON o.gid = b.t) x WHERE n > 1'
            for label in _SLUG_WRITE_LABELS
        ),
        'WP3.0',
    ),
    _rule(
        'E31',
        'Conversations whose user_email matches no User',
        'skipped',
        f'SELECT {_ID} AS id FROM {{Conversation}} v WHERE NOT EXISTS'
        " (SELECT 1 FROM {User} u WHERE u.p->>'email' = v.p->>'user_email')",
        'WP2.8',
    ),
    _rule(
        'E32',
        'Embedding rows of Component or Role',
        'skipped',
        f'SELECT {_EMBEDDING_ID} AS id FROM public.embeddings e'
        " WHERE e.node_label IN ('Component', 'Role')",
        'WP2.10',
        requires=('public.embeddings',),
    ),
    _rule(
        'E33',
        'Archived conversations: archived_at is updated_at',
        'changed',
        f'SELECT {_ID} AS id FROM {{Conversation}} v'
        " WHERE v.p->'is_archived' = 'true'::jsonb",
        'WP2.8',
    ),
    _rule(
        'E34',
        'TokenMetadata nodes: the id is not loaded, jti is the key',
        'changed',
        f'SELECT {_ID} AS id FROM {{TokenMetadata}} v',
        'WP2.3',
    ),
    _rule(
        'E35',
        'Tag.icon values that are not NULL: not loaded',
        'changed',
        f'SELECT {_ID} AS id FROM {{Tag}} v'
        " WHERE nullif(v.p->'icon', 'null'::jsonb) IS NOT NULL",
        'WP1.5',
    ),
]

#: Schema rules whose rows an Appendix E rule already decides. The
#: schema rule then takes the fate of that rule.
COVERED: dict[str, str] = {
    'schema:environments.unique.environments_organization_id_slug_key': 'E39',
    'schema:project_types.unique.project_types_organization_id_slug_key': (
        'E39'
    ),
    'schema:tags.unique.tags_organization_id_slug_key': 'E39',
    'schema:document_templates.unique.'
    'document_templates_organization_id_slug_key': 'E39',
    'schema:releases.check.tag_not_empty': 'E38.release_tag',
    'schema:comment_threads.document_id.not_null': 'E37.CommentThread',
    'schema:comment_threads.organization_id.not_null': 'E37.CommentThread',
    'schema:comments.organization_id.not_null': 'E37.CommentThread',
    'schema:users.unique.users_email_idx': 'E5',
    'schema:identity_connections.unique.'
    'identity_connections_integration_id_subject_key': 'E11',
    'schema:identity_connections.fk.'
    'identity_connections_integration_id_fkey': 'E12',
    'schema:projects.team_id.not_null': 'E8',
    'schema:projects.organization_id.not_null': 'E8',
    'schema:releases.project_id.not_null': 'E15.Release',
    'schema:releases.organization_id.not_null': 'E15.Release',
    'schema:releases.unique.releases_project_tag_idx': 'E14.tag',
    'schema:releases.unique.releases_project_commit_idx': 'E14.commit',
    'schema:deployments.project_id.not_null': 'E15.Deployment',
    'schema:deployments.organization_id.not_null': 'E15.Deployment',
    'schema:deployments.environment_id.not_null': 'E16',
    'schema:blockers.release_id.not_null': 'E15.Blocker',
    'schema:blockers.organization_id.not_null': 'E15.Blocker',
    'schema:blockers.unique.blockers_open_ref_idx': 'E20',
    'schema:template_project_types.project_type_id.not_null': 'E23',
    'schema:integrations.check.login_is_instance': 'E25',
    'schema:webhook_rules.check.handler_valid': 'E26',
    'schema:conversations.user_id.not_null': 'E31',
}
