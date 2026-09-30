"""The source query of each table: the rows that the ETL would insert.

Each query uses the placeholder dialect of ``rules.py``. It returns
``_src`` (text: the graph id of the source row) and one ``jsonb`` column
for each table column that has a graph source, with the raw graph value.
``checks.py`` converts the values and checks the schema rules on them.

These queries show the data to the audit. They are not the ETL
mappings: the Wave 2 work packages write those. Where a query computes
a column, it follows the rule of plan Appendix E or of the README.

The property names come from the code that writes each label (plan
WP1.9 research, 2026-09-30). A table that is not here has no graph
source (``tenants``, ``component_overrides``,
``component_release_overrides``) or is listed in ``NOT_COVERED``.
"""

# The queries are constants of this module. They take no input: the
# graph name goes in with sql.Identifier (rules.expand).
# ruff: noqa: S608

from imbi.common.db.etl.audit import checks

#: The one organization (plan O2) for labels with no organization.
ONE_ORG = (
    "(SELECT o.p->'id' FROM {Organization} o ORDER BY o.p->>'id' LIMIT 1)"
)

#: The organization of each project: Project -OWNED_BY-> Team
#: -BELONGS_TO-> Organization. The newest OWNED_BY edge wins.
PROJECT_ORG = (
    'own AS (SELECT DISTINCT ON (ob.s) ob.s AS project_gid,'
    " t.p->'id' AS team_id, o.p->'id' AS organization_id"
    ' FROM {OWNED_BY} ob JOIN {Team} t ON t.gid = ob.t'
    ' LEFT JOIN ({BELONGS_TO} tb JOIN {Organization} o ON o.gid = tb.t)'
    ' ON tb.s = t.gid ORDER BY ob.s, ob.gid DESC)'
)

#: The organization of each document, from its ATTACHED_TO target.
DOCUMENT_ORG = (
    'doc_org AS (SELECT DISTINCT ON (d.gid) d.gid, d.p, CASE'
    " WHEN pr.gid IS NOT NULL THEN (SELECT o.p->'id' FROM {OWNED_BY} ob"
    ' JOIN {Team} tm ON tm.gid = ob.t JOIN {BELONGS_TO} b ON b.s = tm.gid'
    ' JOIN {Organization} o ON o.gid = b.t WHERE ob.s = pr.gid'
    " ORDER BY o.p->>'id' LIMIT 1)"
    " WHEN pt.gid IS NOT NULL THEN (SELECT o.p->'id' FROM {BELONGS_TO} b"
    ' JOIN {Organization} o ON o.gid = b.t WHERE b.s = pt.gid'
    " ORDER BY o.p->>'id' LIMIT 1)"
    f' WHEN u.gid IS NOT NULL THEN {ONE_ORG}'
    ' END AS organization_id'
    ' FROM {Document} d LEFT JOIN {ATTACHED_TO} a ON a.s = d.gid'
    ' LEFT JOIN {Project} pr ON pr.gid = a.t'
    ' LEFT JOIN {ProjectType} pt ON pt.gid = a.t'
    ' LEFT JOIN {User} u ON u.gid = a.t ORDER BY d.gid, a.gid)'
)

#: The organization of a vertex ``v`` with a BELONGS_TO edge.
BELONGS_TO_ORG = (
    ' LEFT JOIN ({BELONGS_TO} bo JOIN {Organization} o ON o.gid = bo.t)'
    ' ON bo.s = v.gid'
)


def _decoded(value: str) -> str:
    """SQL that decodes JSON text in *value*, as the ETL does (E30)."""
    return (
        f"(CASE WHEN jsonb_typeof({value}) = 'string'"
        f" AND pg_input_is_valid({value} #>> '{{{{}}}}', 'jsonb')"
        f" THEN ({value} #>> '{{{{}}}}')::jsonb ELSE {value} END)"
    )


def _source(table: str, acts_on: str, query: str) -> checks.Source:
    return checks.Source(table=table, query=query, acts_on=acts_on)


_PROJECT_KEYS = (
    "'id','name','slug','description','icon','links','identifiers',"
    "'score','previous_score','created_at','updated_at','archived',"
    "'archived_at','drift_verdicts_at','relationships',"
    "'commit_sync_status','commit_sync_at','commit_sync_by',"
    "'commit_sync_commits','commit_sync_tags','commit_sync_error',"
    "'deployment_sync_status','deployment_sync_at','deployment_sync_by',"
    "'deployment_sync_observed','deployment_sync_releases_created',"
    "'deployment_sync_releases_updated','deployment_sync_events',"
    "'deployment_sync_errors','deployment_sync_error',"
    "'pr_sync_status','pr_sync_at','pr_sync_by','pr_sync_prs',"
    "'pr_sync_error','promote_status','promote_at','promote_by',"
    "'promote_tag','promote_committish','promote_environment',"
    "'promote_from_environment','promote_run_id','promote_run_url',"
    "'promote_error'"
)

BLUEPRINT_ENV_KEYS = (
    'bp_keys AS (SELECT DISTINCT k.key FROM {Blueprint} b'
    ' CROSS JOIN LATERAL jsonb_object_keys(CASE WHEN jsonb_typeof('
    + _decoded("b.p->'json_schema'")
    + "->'properties') = 'object' THEN "
    + _decoded("b.p->'json_schema'")
    + "->'properties' ELSE '{{}}'::jsonb END) AS k(key)"
    " WHERE b.p->>'kind' = 'relationship' AND b.p->>'source' = 'Project'"
    " AND b.p->>'target' = 'Environment' AND b.p->>'edge' = 'DEPLOYED_IN'"
    " AND coalesce(b.p->'enabled', 'true'::jsonb) = 'true'::jsonb)"
)

_SYNC = (
    "SELECT own.organization_id, v.p->'id' AS project_id,"
    " to_jsonb('{kind}'::text) AS sync_type,"
    " v.p->'{prefix}_status' AS sync_status,"
    " v.p->'{prefix}_at' AS status_at, v.p->'{prefix}_by' AS status_by,"
    ' jsonb_strip_nulls(jsonb_build_object({result})) AS result,'
    " v.p->'{prefix}_error' AS error,"
    " (v.p->>'id') || '/{kind}' AS _src"
    ' FROM {{Project}} v LEFT JOIN own ON own.project_gid = v.gid'
    ' WHERE num_nonnulls({keys}) > 0'
)


def _sync(kind: str, prefix: str, results: dict[str, str]) -> str:
    keys = ['status', 'at', 'by', 'error', *results.values()]
    return _SYNC.format(
        kind=kind,
        prefix=prefix,
        result=', '.join(
            f"'{name}', v.p->'{prefix}_{key}'" for name, key in results.items()
        ),
        keys=', '.join(f"v.p->'{prefix}_{key}'" for key in keys),
    )


def _promotion_environment(key: str) -> str:
    return (
        "(SELECT x.p->'id' FROM env x"
        ' WHERE x.org_id = own.organization_id'
        f" AND x.p->>'slug' = NULLIF(v.p->>'{key}', '')"
        " ORDER BY x.p->>'id' LIMIT 1)"
    )


DELIVERY = [
    _source(
        'projects',
        'WP2.2',
        'WITH ' + PROJECT_ORG + ' SELECT own.organization_id,'
        " v.p->'id' AS id, own.team_id,"
        " v.p->'name' AS name, v.p->'slug' AS slug,"
        " v.p->'description' AS description, v.p->'icon' AS icon,"
        " v.p->'links' AS links, v.p->'identifiers' AS identifiers,"
        f' v.p - ARRAY[{_PROJECT_KEYS}]::text[] AS attributes,'
        " v.p->'score' AS score, v.p->'previous_score' AS previous_score,"
        " CASE WHEN v.p->'archived_at' IS NOT NULL"
        " AND v.p->'archived_at' <> 'null'::jsonb THEN v.p->'archived_at'"
        " WHEN v.p->'archived' = 'true'::jsonb"
        " THEN coalesce(v.p->'updated_at', v.p->'created_at')"
        ' END AS archived_at,'
        " v.p->'drift_verdicts_at' AS drift_verdicts_at,"
        " v.p->'created_at' AS created_at, v.p->'updated_at' AS updated_at,"
        " v.p->>'id' AS _src"
        ' FROM {Project} v LEFT JOIN own ON own.project_gid = v.gid',
    ),
    _source(
        'project_type_assignments',
        'WP2.2',
        'WITH ' + PROJECT_ORG + ', ty AS (SELECT DISTINCT ON (e.s, e.t)'
        ' e.s, e.t FROM {TYPE} e ORDER BY e.s, e.t, e.gid DESC)'
        " SELECT own.organization_id, v.p->'id' AS project_id,"
        " pt.p->'id' AS project_type_id,"
        " (v.p->>'id') || '/' || (pt.p->>'id') AS _src"
        ' FROM ty JOIN {Project} v ON v.gid = ty.s'
        ' JOIN {ProjectType} pt ON pt.gid = ty.t'
        ' LEFT JOIN own ON own.project_gid = v.gid',
    ),
    _source(
        'project_environments',
        'WP2.4',
        'WITH ' + PROJECT_ORG + ', di AS (SELECT DISTINCT ON (e.s, e.t)'
        ' e.s, e.t, e.p FROM {DEPLOYED_IN} e ORDER BY e.s, e.t, e.gid DESC),'
        + BLUEPRINT_ENV_KEYS
        + " SELECT own.organization_id, v.p->'id' AS project_id,"
        " env.p->'id' AS environment_id,"
        ' (SELECT coalesce(jsonb_object_agg(kv.key, kv.value),'
        " '{{}}'::jsonb) FROM jsonb_each(di.p) kv"
        ' WHERE kv.key IN (SELECT key FROM bp_keys)) AS attributes,'
        " (SELECT r.p->'id' FROM {Release} r"
        " WHERE r.p->'id' = di.p->'current_release' LIMIT 1)"
        ' AS current_release_id,'
        " di.p->'current_release_at' AS current_release_at,"
        " di.p->'current_deployment_external_id'"
        ' AS current_deployment_external_id,'
        " di.p->'current_state_source' AS current_state_source,"
        " di.p->'current_state_observed_at' AS current_state_observed_at,"
        " (v.p->>'id') || '/' || (env.p->>'id') AS _src"
        ' FROM di JOIN {Project} v ON v.gid = di.s'
        ' JOIN {Environment} env ON env.gid = di.t'
        ' LEFT JOIN own ON own.project_gid = v.gid',
    ),
    _source(
        'project_dependencies',
        'WP2.2',
        'WITH ' + PROJECT_ORG + ' SELECT own.organization_id,'
        " src.p->'id' AS project_id, tgt.p->'id' AS dependency_id,"
        " (src.p->>'id') || '/' || (tgt.p->>'id') AS _src"
        ' FROM {DEPENDS_ON} e JOIN {Project} src ON src.gid = e.s'
        ' JOIN {Project} tgt ON tgt.gid = e.t'
        ' LEFT JOIN own ON own.project_gid = src.gid',
    ),
    _source(
        'project_syncs',
        'WP2.2',
        'WITH '
        + PROJECT_ORG
        + ' '
        + ' UNION ALL '.join(
            [
                _sync(
                    'commit',
                    'commit_sync',
                    {'commits': 'commits', 'tags': 'tags'},
                ),
                _sync(
                    'deployment',
                    'deployment_sync',
                    {
                        'observed': 'observed',
                        'releases_created': 'releases_created',
                        'releases_updated': 'releases_updated',
                        'events': 'events',
                        'errors': 'errors',
                    },
                ),
                _sync('pull_request', 'pr_sync', {'prs': 'prs'}),
            ]
        ),
    ),
    _source(
        'project_promotions',
        'WP2.2',
        'WITH ' + PROJECT_ORG + ", env AS (SELECT e.p, o.p->'id' AS org_id"
        ' FROM {Environment} e JOIN {BELONGS_TO} b ON b.s = e.gid'
        ' JOIN {Organization} o ON o.gid = b.t)'
        " SELECT own.organization_id, v.p->'id' AS project_id,"
        " v.p->'promote_status' AS promotion_status,"
        " v.p->'promote_at' AS status_at, v.p->'promote_by' AS status_by,"
        " v.p->'promote_tag' AS tag,"
        " v.p->'promote_committish' AS committish, "
        + _promotion_environment('promote_environment')
        + ' AS environment_id, '
        + _promotion_environment('promote_from_environment')
        + ' AS from_environment_id,'
        " v.p->'promote_run_id' AS run_id,"
        " v.p->'promote_run_url' AS run_url,"
        " v.p->'promote_error' AS error, v.p->>'id' AS _src"
        ' FROM {Project} v LEFT JOIN own ON own.project_gid = v.gid'
        " WHERE num_nonnulls(v.p->'promote_status', v.p->'promote_at',"
        " v.p->'promote_by', v.p->'promote_tag', v.p->'promote_committish',"
        " v.p->'promote_environment', v.p->'promote_from_environment',"
        " v.p->'promote_run_id', v.p->'promote_run_url',"
        " v.p->'promote_error') > 0",
    ),
    _source(
        'releases',
        'WP2.4',
        'WITH ' + PROJECT_ORG + ', hr AS (SELECT DISTINCT ON (h.t)'
        " h.t AS release_gid, v.p->'id' AS project_id,"
        ' own.organization_id FROM {HAS_RELEASE} h'
        ' JOIN {Project} v ON v.gid = h.s'
        ' LEFT JOIN own ON own.project_gid = v.gid'
        ' ORDER BY h.t, h.gid DESC)'
        " SELECT hr.organization_id, r.p->'id' AS id, hr.project_id,"
        " r.p->'tag' AS tag, r.p->'committish' AS committish,"
        " r.p->'promoted_committish' AS promoted_committish,"
        " r.p->'title' AS title, r.p->'description' AS description,"
        " r.p->'links' AS links, r.p->'created_by' AS created_by,"
        " r.p->'workflow_run_id' AS workflow_run_id,"
        " r.p->'workflow_run_url' AS workflow_run_url,"
        " r.p->'ci_status_at_promote' AS promote_ci_status,"
        " r.p->'ci_override_by' AS ci_override_by,"
        " r.p->'ci_override_at' AS ci_override_at,"
        " r.p->'drift_detected' AS drift_detected,"
        " r.p->'drift_checked_at' AS drift_checked_at,"
        " r.p->'created_at' AS created_at, r.p->'updated_at' AS updated_at,"
        " r.p->>'id' AS _src"
        ' FROM {Release} r LEFT JOIN hr ON hr.release_gid = r.gid',
    ),
    _source(
        'deployments',
        'WP2.4',
        'WITH ' + PROJECT_ORG + ', bt AS (SELECT DISTINCT ON (b.s)'
        " b.s AS dep_gid, v.p->'id' AS project_id, own.organization_id"
        ' FROM {BELONGS_TO} b JOIN {Project} v ON v.gid = b.t'
        ' LEFT JOIN own ON own.project_gid = v.gid'
        ' ORDER BY b.s, b.gid DESC),'
        ' tg AS (SELECT DISTINCT ON (t.s) t.s AS dep_gid,'
        " e.p->'id' AS environment_id FROM {TARGETS} t"
        ' JOIN {Environment} e ON e.gid = t.t ORDER BY t.s, t.gid DESC),'
        ' hd AS (SELECT DISTINCT ON (h.t) h.t AS dep_gid,'
        " r.p->'id' AS release_id FROM {HAS_DEPLOYMENT} h"
        ' JOIN {Release} r ON r.gid = h.s'
        " ORDER BY h.t, (NULLIF(r.p->>'tag', '') IS NULL), h.gid DESC)"
        " SELECT bt.organization_id, d.p->'id' AS id, bt.project_id,"
        " tg.environment_id, hd.release_id, d.p->'origin' AS origin,"
        " d.p->'status' AS deployment_status, d.p->'note' AS note,"
        " d.p->'external_run_id' AS external_run_id,"
        " d.p->'external_run_url' AS external_run_url,"
        " d.p->'performed_by' AS performed_by,"
        " d.p->'credential' AS credential,"
        " d.p->'release_tag' AS release_tag,"
        " d.p->'release_committish' AS release_committish,"
        " d.p->'history' AS history,"
        " coalesce(d.p->'updated_at', d.p->'created_at') AS transitioned_at,"
        " d.p->'created_at' AS created_at, d.p->'updated_at' AS updated_at,"
        " d.p->>'id' AS _src"
        ' FROM {Deployment} d LEFT JOIN bt ON bt.dep_gid = d.gid'
        ' LEFT JOIN tg ON tg.dep_gid = d.gid'
        ' LEFT JOIN hd ON hd.dep_gid = d.gid',
    ),
    _source(
        'blockers',
        'WP2.4',
        'WITH ' + PROJECT_ORG + ', rel AS (SELECT DISTINCT ON (h.t)'
        ' h.t AS release_gid, own.organization_id FROM {HAS_RELEASE} h'
        ' JOIN {Project} v ON v.gid = h.s'
        ' LEFT JOIN own ON own.project_gid = v.gid'
        ' ORDER BY h.t, h.gid DESC),'
        ' bb AS (SELECT DISTINCT ON (e.t) e.t AS blocker_gid,'
        " r.gid AS release_gid, r.p->'id' AS release_id"
        ' FROM {BLOCKED_BY} e JOIN {Release} r ON r.gid = e.s'
        ' ORDER BY e.t, e.gid DESC)'
        " SELECT rel.organization_id, b.p->'id' AS id, bb.release_id,"
        " b.p->'type' AS blocker_type, b.p->'description' AS description,"
        " b.p->'external_ref' AS external_ref,"
        " b.p->'status' AS blocker_status, b.p->'scope' AS scope,"
        " b.p->'created_by' AS created_by,"
        " b.p->'resolved_by' AS resolved_by,"
        " b.p->'resolved_at' AS resolved_at,"
        " b.p->'resolution_note' AS resolution_note,"
        " b.p->'created_at' AS created_at, b.p->'updated_at' AS updated_at,"
        " b.p->>'id' AS _src"
        ' FROM {Blocker} b LEFT JOIN bb ON bb.blocker_gid = b.gid'
        ' LEFT JOIN rel ON rel.release_gid = bb.release_gid',
    ),
]

_TEMPLATE_ORG = (
    " LEFT JOIN LATERAL (SELECT o.gid AS ogid, o.p->'id' AS oid"
    ' FROM {BELONGS_TO} b JOIN {Organization} o ON o.gid = b.t'
    " WHERE b.s = t.gid ORDER BY o.p->>'id' LIMIT 1) org ON true"
)

CONTENT = [
    _source(
        'components',
        'WP2.5',
        "SELECT c.p->'id' AS id, c.p->'purl_name' AS purl_name,"
        " c.p->'name' AS name, c.p->'ecosystem' AS ecosystem,"
        " c.p->'description' AS description,"
        " c.p->'created_at' AS created_at, c.p->'updated_at' AS updated_at,"
        " c.p->>'id' AS _src FROM {Component} c",
    ),
    _source(
        'component_releases',
        'WP2.5',
        "SELECT cr.p->'id' AS id, c.p->'id' AS component_id,"
        " cr.p->'version' AS version, cr.p->'license' AS license,"
        " cr.p->'supplier' AS supplier, cr.p->'hashes' AS hashes,"
        " cr.p->'created_at' AS created_at,"
        " cr.p->'updated_at' AS updated_at, cr.p->>'id' AS _src"
        ' FROM {ComponentRelease} cr'
        ' LEFT JOIN ({HAS_RELEASE} e JOIN {Component} c ON c.gid = e.s)'
        ' ON e.t = cr.gid',
    ),
    _source(
        'component_identifiers',
        'WP2.5',
        "SELECT DISTINCT ON (ci.gid) ci.p->'id' AS id,"
        " c.p->'id' AS component_id, ci.p->'kind' AS kind,"
        " ci.p->'value' AS value, ci.p->'created_at' AS created_at,"
        " ci.p->'updated_at' AS updated_at, ci.p->>'id' AS _src"
        ' FROM {ComponentIdentifier} ci'
        ' LEFT JOIN ({IDENTIFIED_BY} e JOIN {Component} c ON c.gid = e.s)'
        ' ON e.t = ci.gid'
        " ORDER BY ci.gid, CASE WHEN pg_input_is_valid(c.p->>'created_at',"
        " 'timestamptz') THEN (c.p->>'created_at')::timestamptz END"
        " NULLS LAST, c.p->>'id'",
    ),
    _source(
        'advisories',
        'WP2.5',
        "SELECT a.p->'id' AS id, a.p->'cve_id' AS cve_id,"
        " a.p->'created_at' AS created_at, a.p->>'id' AS _src"
        ' FROM {Advisory} a',
    ),
    _source(
        'component_governance',
        'WP2.5',
        f'SELECT {ONE_ORG} AS organization_id,'
        " c.p->'id' AS component_id, c.p->'status' AS governance_status,"
        " c.p->'status_by' AS status_by, c.p->'status_at' AS status_at,"
        " c.p->>'id' AS _src FROM {Component} c"
        " WHERE c.p->'status' IS NOT NULL AND c.p->'status' <> 'null'::jsonb",
    ),
    _source(
        'component_release_governance',
        'WP2.5',
        f'SELECT {ONE_ORG} AS organization_id,'
        " cr.p->'id' AS component_release_id,"
        " cr.p->'status' AS governance_status,"
        " cr.p->'status_by' AS status_by, cr.p->'status_at' AS status_at,"
        " cr.p->>'id' AS _src FROM {ComponentRelease} cr"
        " WHERE cr.p->'status' IS NOT NULL"
        " AND cr.p->'status' <> 'null'::jsonb",
    ),
    _source(
        'component_notes',
        'WP2.5',
        f"SELECT n.p->'id' AS id, {ONE_ORG} AS organization_id,"
        " cr.p->'id' AS component_release_id, n.p->'author' AS author,"
        " n.p->'body' AS body, n.p->'created_at' AS created_at,"
        " n.p->>'id' AS _src FROM {ComponentNote} n"
        ' LEFT JOIN ({HAS_NOTE} e JOIN {ComponentRelease} cr'
        ' ON cr.gid = e.s) ON e.t = n.gid',
    ),
    _source(
        'component_advisories',
        'WP2.5',
        f'SELECT {ONE_ORG} AS organization_id,'
        " cr.p->'id' AS component_release_id, a.p->'id' AS advisory_id,"
        " a.p->'url' AS url, a.p->'title' AS title,"
        " a.p->'created_by' AS created_by, a.p->'created_at' AS created_at,"
        " a.p->'updated_at' AS updated_at,"
        " (cr.p->>'id') || '/' || (a.p->>'id') AS _src"
        ' FROM {HAS_ADVISORY} e'
        ' JOIN {ComponentRelease} cr ON cr.gid = e.s'
        ' JOIN {Advisory} a ON a.gid = e.t',
    ),
    _source(
        'documents',
        'WP2.6',
        'WITH ' + DOCUMENT_ORG + " SELECT d.p->'id' AS id,"
        " dd.organization_id, pr.p->'id' AS project_id,"
        " pt.p->'id' AS project_type_id, u.p->'id' AS user_id,"
        " d.p->'title' AS title, d.p->'content' AS content,"
        " d.p->'is_pinned' AS is_pinned, d.p->'version' AS version,"
        " d.p->'created_by' AS created_by, d.p->'updated_by' AS updated_by,"
        " d.p->'created_at' AS created_at, d.p->'updated_at' AS updated_at,"
        " d.p->>'id' AS _src FROM {Document} d"
        ' LEFT JOIN doc_org dd ON dd.gid = d.gid'
        ' LEFT JOIN {ATTACHED_TO} a ON a.s = d.gid'
        ' LEFT JOIN {Project} pr ON pr.gid = a.t'
        ' LEFT JOIN {ProjectType} pt ON pt.gid = a.t'
        ' LEFT JOIN {User} u ON u.gid = a.t',
    ),
    _source(
        'document_tags',
        'WP2.6',
        'WITH ' + DOCUMENT_ORG + ' SELECT dd.organization_id,'
        " dd.p->'id' AS document_id, tg.p->'id' AS tag_id,"
        " (dd.p->>'id') || '/' || (tg.p->>'id') AS _src"
        ' FROM {TAGGED_WITH} e JOIN doc_org dd ON dd.gid = e.s'
        ' JOIN {Tag} tg ON tg.gid = e.t',
    ),
    _source(
        'document_likes',
        'WP2.6',
        'WITH ' + DOCUMENT_ORG + ' SELECT dd.organization_id,'
        " dd.p->'id' AS document_id, lu.p->'id' AS user_id,"
        " e.p->'at' AS liked_at,"
        " (dd.p->>'id') || '/' || (lu.p->>'id') AS _src"
        ' FROM {LIKED} e JOIN {User} lu ON lu.gid = e.s'
        ' JOIN doc_org dd ON dd.gid = e.t',
    ),
    _source(
        'document_templates',
        'WP2.6',
        "SELECT org.oid AS organization_id, t.p->'name' AS name,"
        " t.p->'slug' AS slug, t.p->'description' AS description,"
        " t.p->'icon' AS icon, t.p->'type' AS template_type,"
        " t.p->'title' AS title, t.p->'content' AS content,"
        " t.p->'sort_order' AS sort_order,"
        " t.p->'created_at' AS created_at, t.p->'updated_at' AS updated_at,"
        " coalesce(org.oid #>> '{{}}', '?') || '/' || (t.p->>'id') AS _src"
        ' FROM {DocumentTemplate} t' + _TEMPLATE_ORG,
    ),
    _source(
        'template_project_types',
        'WP2.6',
        'SELECT org.oid AS organization_id, ptn.pid AS project_type_id,'
        " coalesce(org.oid #>> '{{}}', '?') || '/' || (t.p->>'id')"
        " || '/' || s.slug AS _src FROM {DocumentTemplate} t"
        + _TEMPLATE_ORG
        + ' CROSS JOIN LATERAL jsonb_array_elements_text(CASE WHEN'
        " jsonb_typeof(t.p->'project_type_slugs') = 'array'"
        " THEN t.p->'project_type_slugs' ELSE '[]'::jsonb END) AS s(slug)"
        " LEFT JOIN LATERAL (SELECT pt.p->'id' AS pid FROM {ProjectType} pt"
        ' JOIN {BELONGS_TO} pb ON pb.s = pt.gid WHERE pb.t = org.ogid'
        " AND pt.p->>'slug' = s.slug ORDER BY pt.p->>'id' LIMIT 1) ptn"
        ' ON true',
    ),
    _source(
        'template_tags',
        'WP2.6',
        "SELECT org.oid AS organization_id, tg.p->'id' AS tag_id,"
        " coalesce(org.oid #>> '{{}}', '?') || '/' || (t.p->>'id')"
        " || '/' || (tg.p->>'id') AS _src"
        ' FROM {TAGGED_WITH} e JOIN {DocumentTemplate} t ON t.gid = e.s'
        ' JOIN {Tag} tg ON tg.gid = e.t' + _TEMPLATE_ORG,
    ),
    _source(
        'comment_threads',
        'WP2.6',
        'WITH ' + DOCUMENT_ORG + " SELECT t.p->'id' AS id,"
        " dd.organization_id, dd.p->'id' AS document_id,"
        " t.p->'kind' AS kind, t.p->'anchor_quote' AS anchor_quote,"
        " t.p->'anchor_prefix' AS anchor_prefix,"
        " t.p->'anchor_suffix' AS anchor_suffix,"
        " t.p->'anchor_start' AS anchor_start,"
        " t.p->'resolved_by' AS resolved_by,"
        " CASE WHEN nullif(t.p->'resolved_at', 'null'::jsonb) IS NOT NULL"
        " THEN t.p->'resolved_at' WHEN t.p->'resolved' = 'true'::jsonb"
        " THEN coalesce(nullif(t.p->'updated_at', 'null'::jsonb),"
        " t.p->'created_at') END AS resolved_at,"
        " t.p->'created_by' AS created_by, t.p->'created_at' AS created_at,"
        " t.p->'updated_at' AS updated_at, t.p->>'id' AS _src"
        ' FROM {CommentThread} t LEFT JOIN {ON_DOCUMENT} e ON e.s = t.gid'
        ' LEFT JOIN doc_org dd ON dd.gid = e.t',
    ),
    _source(
        'comments',
        'WP2.6',
        'WITH ' + DOCUMENT_ORG + " SELECT c.p->'id' AS id,"
        " dd.organization_id, t.p->'id' AS thread_id,"
        " c.p->'author' AS author, c.p->'body' AS body,"
        " c.p->'mentions' AS mentions,"
        " c.p->'acknowledged_by' AS acknowledged_by,"
        " c.p->'edited' AS edited, c.p->'created_at' AS created_at,"
        " c.p->'updated_at' AS updated_at, c.p->>'id' AS _src"
        ' FROM {Comment} c LEFT JOIN {IN_THREAD} it ON it.s = c.gid'
        ' LEFT JOIN {CommentThread} t ON t.gid = it.t'
        ' LEFT JOIN {ON_DOCUMENT} od ON od.s = t.gid'
        ' LEFT JOIN doc_org dd ON dd.gid = od.t',
    ),
    _source(
        'uploads',
        'WP2.6',
        f"SELECT u.p->'id' AS id, {ONE_ORG} AS organization_id,"
        " u.p->'filename' AS filename, u.p->'content_type' AS content_type,"
        " u.p->'size' AS file_size, u.p->'s3_key' AS storage_key,"
        " u.p->'thumbnail_s3_key' AS thumbnail_storage_key,"
        " u.p->'uploaded_by' AS uploaded_by,"
        " u.p->'created_at' AS created_at, u.p->>'id' AS _src"
        ' FROM {Upload} u',
    ),
]

_PROJECT_EDGE_ORG = (
    ' LEFT JOIN ({OWNED_BY} ob JOIN {Team} tm ON tm.gid = ob.t'
    ' JOIN {BELONGS_TO} tb ON tb.s = tm.gid'
    ' JOIN {Organization} o ON o.gid = tb.t) ON ob.s = pr.gid'
)

_SCORING_MAPS = (
    "'value_score_map', 'range_score_map', 'age_score_map',"
    " 'status_score_map', 'condition'"
)

_CAPABILITY_COLUMNS = (
    " u.p->'capability' AS capability, u.p->'default' AS is_default,"
    " u.p->'options' AS options, u.p->'env_payloads' AS environment_payloads,"
    " u.p->'identity_integration_id' AS identity_integration_id,"
)

INTEGRATIONS = [
    _source(
        'integrations',
        'WP2.7',
        "SELECT v.p->'id' AS id, o.p->'id' AS organization_id,"
        " t.p->'id' AS team_id, v.p->'plugin' AS plugin_slug,"
        " v.p->'name' AS name, v.p->'slug' AS slug,"
        " v.p->'description' AS description, v.p->'icon' AS icon,"
        " v.p->'options' AS options,"
        " v.p->'encrypted_credentials' AS credentials_encrypted,"
        " v.p->'capabilities' AS capabilities,"
        " v.p->'used_as_login' AS used_as_login, v.p->'vendor' AS vendor,"
        " v.p->'service_url' AS service_url, v.p->'category' AS category,"
        " v.p->'status' AS integration_status, v.p->'links' AS links,"
        " v.p->'identifiers' AS identifiers,"
        " v.p->'created_at' AS created_at, v.p->'updated_at' AS updated_at,"
        " v.p->>'id' AS _src FROM {Integration} v"
        + BELONGS_TO_ORG
        + ' LEFT JOIN ({MANAGED_BY} mb JOIN {Team} t ON t.gid = mb.t)'
        ' ON mb.s = v.gid',
    ),
    _source(
        'project_integrations',
        'WP2.7',
        "SELECT o.p->'id' AS organization_id, pr.p->'id' AS project_id,"
        " i.p->'id' AS integration_id, e.p->'identifier' AS identifier,"
        " e.p->'canonical_url' AS canonical_url,"
        " e.p->'webhook_secret_enc' AS webhook_secret_encrypted,"
        " (pr.p->>'id') || '/' || (i.p->>'id') AS _src"
        ' FROM {EXISTS_IN} e JOIN {Project} pr ON pr.gid = e.s'
        ' JOIN {Integration} i ON i.gid = e.t' + _PROJECT_EDGE_ORG,
    ),
    _source(
        'project_capabilities',
        'WP2.7',
        "SELECT o.p->'id' AS organization_id, pr.p->'id' AS project_id,"
        " i.p->'id' AS integration_id,"
        + _CAPABILITY_COLUMNS
        + " (pr.p->>'id') || '/' || (i.p->>'id') || '/'"
        " || coalesce(u.p->>'capability', '') AS _src"
        ' FROM {USES} u JOIN {Project} pr ON pr.gid = u.s'
        ' JOIN {Integration} i ON i.gid = u.t' + _PROJECT_EDGE_ORG,
    ),
    _source(
        'project_type_capabilities',
        'WP2.7',
        "SELECT o.p->'id' AS organization_id,"
        " v.p->'id' AS project_type_id, i.p->'id' AS integration_id,"
        + _CAPABILITY_COLUMNS
        + " (v.p->>'id') || '/' || (i.p->>'id') || '/'"
        " || coalesce(u.p->>'capability', '') AS _src"
        ' FROM {USES} u JOIN {ProjectType} v ON v.gid = u.s'
        ' JOIN {Integration} i ON i.gid = u.t' + BELONGS_TO_ORG,
    ),
    _source(
        'webhooks',
        'WP2.7',
        "SELECT v.p->'id' AS id, o.p->'id' AS organization_id,"
        " v.p->'name' AS name, v.p->'slug' AS slug,"
        " v.p->'description' AS description, v.p->'icon' AS icon,"
        " i.p->'id' AS integration_id, v.p->'secret' AS secret_encrypted,"
        " ib.p->'identifier_selector' AS identifier_selector,"
        " ib.p->'user_subject_selector' AS user_subject_selector,"
        " ib.p->'user_type_selector' AS user_type_selector,"
        " coalesce((SELECT oi.p->'id' FROM {Integration} oi"
        ' JOIN {BELONGS_TO} ob2 ON ob2.s = oi.gid WHERE ob2.t = o.gid'
        " AND oi.p->>'slug' = ib.p->>'identity_integration_slug' LIMIT 1),"
        " (SELECT gi.p->'id' FROM {Integration} gi"
        " WHERE gi.p->>'slug' = ib.p->>'identity_integration_slug'"
        ' AND NOT EXISTS (SELECT 1 FROM {BELONGS_TO} gb'
        ' WHERE gb.s = gi.gid) LIMIT 1)) AS identity_integration_id,'
        " ib.p->'event_type_selector' AS event_type_selector,"
        " v.p->'created_at' AS created_at, v.p->'updated_at' AS updated_at,"
        " v.p->>'id' AS _src FROM {Webhook} v"
        + BELONGS_TO_ORG
        + ' LEFT JOIN ({IMPLEMENTED_BY} ib JOIN {Integration} i'
        ' ON i.gid = ib.t) ON ib.s = v.gid',
    ),
    _source(
        'webhook_rules',
        'WP2.7',
        "SELECT o.p->'id' AS organization_id, w.p->'id' AS webhook_id,"
        " r.p->'ordinal' AS ordinal,"
        " r.p->'filter_expression' AS filter_expression,"
        " r.p->'handler' AS handler, r.p->'handler_config' AS handler_config,"
        " coalesce(w.p->>'id', '?') || '/' || coalesce(r.p->>'ordinal', '?')"
        ' AS _src FROM {WebhookRule} r'
        ' LEFT JOIN ({ACTIONS} a JOIN {Webhook} w ON w.gid = a.t)'
        ' ON a.s = r.gid'
        ' LEFT JOIN ({BELONGS_TO} bo JOIN {Organization} o ON o.gid = bo.t)'
        ' ON bo.s = w.gid',
    ),
    _source(
        'plugin_registrations',
        'WP2.7',
        "SELECT r.p->'slug' AS slug, r.p->'enabled' AS enabled,"
        " r.p->>'slug' AS _src FROM {PluginRegistration} r"
        " UNION ALL SELECT DISTINCT i.p->'plugin' AS slug,"
        " to_jsonb(false) AS enabled, 'E24:' || coalesce(i.p->>'plugin', '')"
        ' AS _src FROM {Integration} i WHERE NOT EXISTS (SELECT 1'
        " FROM {PluginRegistration} r2 WHERE r2.p->>'slug' = i.p->>'plugin')",
    ),
    _source(
        'plugin_entities',
        'WP2.9',
        f"SELECT a.p->'id' AS id, {ONE_ORG} AS organization_id,"
        " to_jsonb('aws'::text) AS plugin_slug,"
        " to_jsonb('AwsAccount'::text) AS label, (a.p - 'id') AS data,"
        " a.p->>'id' AS _src FROM {AwsAccount} a",
    ),
    _source(
        'plugin_edges',
        'WP2.9',
        "SELECT o.p->'id' AS organization_id,"
        " to_jsonb('aws'::text) AS plugin_slug,"
        " to_jsonb('MAPS_TO'::text) AS edge_type,"
        " to_jsonb('Environment'::text) AS source_label,"
        " v.p->'id' AS source_id, to_jsonb('AwsAccount'::text)"
        " AS target_label, acct.p->'id' AS target_id, m.p AS properties,"
        " coalesce(v.p->>'id', '?') || '/MAPS_TO/'"
        " || coalesce(acct.p->>'id', '?') AS _src FROM {MAPS_TO} m"
        ' LEFT JOIN {Environment} v ON v.gid = m.s'
        ' LEFT JOIN {AwsAccount} acct ON acct.gid = m.t' + BELONGS_TO_ORG,
    ),
    _source(
        'ai_providers',
        'WP2.8',
        "SELECT v.p->'id' AS id, o.p->'id' AS organization_id,"
        " v.p->'name' AS name, v.p->'slug' AS slug,"
        " v.p->'description' AS description, v.p->'icon' AS icon,"
        " v.p->'driver' AS driver, v.p->'base_url' AS base_url,"
        " v.p->'enabled' AS enabled,"
        " v.p->'credentials_encrypted' AS credentials_encrypted,"
        " v.p->'credential_hint' AS credential_hint,"
        " v.p->'credential_updated_at' AS credential_updated_at,"
        " v.p->'region' AS region, v.p->'project_id' AS cloud_project_id,"
        " v.p->'created_at' AS created_at, v.p->'updated_at' AS updated_at,"
        " v.p->>'id' AS _src FROM {AIProvider} v" + BELONGS_TO_ORG,
    ),
    _source(
        'ai_models',
        'WP2.8',
        "SELECT v.p->'id' AS id, o.p->'id' AS organization_id,"
        " v.p->'name' AS name, v.p->'slug' AS slug,"
        " v.p->'description' AS description, v.p->'icon' AS icon,"
        " pv.p->'id' AS provider_id, v.p->'model_id' AS provider_model_id,"
        " v.p->'kind' AS kind, v.p->'enabled' AS enabled,"
        " v.p->'access_scope' AS access_scope,"
        " v.p->'context_window' AS context_window,"
        " v.p->'max_output_tokens' AS max_output_tokens,"
        " v.p->'input_cost_per_million' AS input_cost_per_million,"
        " v.p->'output_cost_per_million' AS output_cost_per_million,"
        " v.p->'default_temperature' AS default_temperature,"
        " v.p->'default_top_p' AS default_top_p,"
        " v.p->'monthly_spend_cap' AS monthly_spend_cap,"
        " v.p->'created_at' AS created_at, v.p->'updated_at' AS updated_at,"
        " v.p->>'id' AS _src FROM {AIModel} v"
        + BELONGS_TO_ORG
        + ' LEFT JOIN ({SERVED_BY} sb JOIN {AIProvider} pv'
        ' ON pv.gid = sb.t) ON sb.s = v.gid',
    ),
    _source(
        'ai_model_teams',
        'WP2.8',
        "SELECT o.p->'id' AS organization_id, v.p->'id' AS ai_model_id,"
        " t.p->'id' AS team_id, (v.p->>'id') || '/' || (t.p->>'id') AS _src"
        ' FROM {ALLOWED_FOR} af JOIN {AIModel} v ON v.gid = af.s'
        ' JOIN {Team} t ON t.gid = af.t' + BELONGS_TO_ORG,
    ),
    _source(
        'mcp_servers',
        'WP2.8',
        f"SELECT v.p->'id' AS id, {ONE_ORG} AS organization_id,"
        " v.p->'name' AS name, v.p->'slug' AS slug,"
        " v.p->'description' AS description, v.p->'icon' AS icon,"
        " v.p->'url' AS url, v.p->'enabled' AS enabled,"
        " v.p->'tool_prefix' AS tool_prefix,"
        " v.p->'timeout' AS timeout_seconds, v.p->'verify_ssl' AS verify_ssl,"
        " v.p->'ignored_tools' AS ignored_tools,"
        " v.p->'auth_type' AS auth_type,"
        " v.p->'static_header' AS static_header,"
        " v.p->'static_value_encrypted' AS static_value_encrypted,"
        " v.p->'oauth_token_url' AS oauth_token_url,"
        " v.p->'oauth_client_id' AS oauth_client_id,"
        " v.p->'oauth_client_secret_encrypted'"
        ' AS oauth_client_secret_encrypted,'
        " v.p->'oauth_scope' AS oauth_scope,"
        " v.p->'status' AS server_status,"
        " v.p->'last_tested_at' AS last_tested_at,"
        " v.p->'last_tested_latency_ms' AS last_tested_latency_ms,"
        " v.p->'tools_discovered' AS tools_discovered_count,"
        " v.p->'last_error' AS last_error,"
        " v.p->'created_at' AS created_at, v.p->'updated_at' AS updated_at,"
        " v.p->>'id' AS _src FROM {MCPServer} v",
    ),
    _source(
        'conversations',
        'WP2.8',
        f"SELECT c.p->'id' AS id, {ONE_ORG} AS organization_id,"
        " (SELECT u.p->'id' FROM {User} u"
        " WHERE u.p->>'email' = c.p->>'user_email'"
        " ORDER BY u.p->>'id' LIMIT 1) AS user_id,"
        " c.p->'title' AS title, c.p->'model' AS model_name,"
        " CASE WHEN c.p->'is_archived' = 'true'::jsonb"
        " THEN c.p->'updated_at' END AS archived_at,"
        " c.p->'created_at' AS created_at, c.p->'updated_at' AS updated_at,"
        " c.p->>'id' AS _src FROM {Conversation} c",
    ),
    _source(
        'messages',
        'WP2.8',
        f"SELECT m.p->'id' AS id, {ONE_ORG} AS organization_id,"
        " c.p->'id' AS conversation_id, m.p->'sequence' AS message_seq,"
        " m.p->'role' AS author_role, m.p->'content' AS content,"
        " m.p->'tool_use' AS tool_use, m.p->'tool_results' AS tool_results,"
        " m.p->'token_usage' AS token_usage,"
        " m.p->'created_at' AS created_at, m.p->>'id' AS _src"
        ' FROM {Message} m'
        ' LEFT JOIN ({CONTAINS} ct JOIN {Conversation} c ON c.gid = ct.s)'
        ' ON ct.t = m.gid',
    ),
    _source(
        'analysis_reports',
        'WP2.8',
        "SELECT r.p->'id' AS id, o.p->'id' AS organization_id,"
        " pr.p->'id' AS project_id, r.p->'overall_status' AS overall_status,"
        " NULLIF(r.p->'triggered_by_user_id', to_jsonb(''::text))"
        ' AS triggered_by,'
        " r.p->'created_at' AS created_at, r.p->>'id' AS _src"
        ' FROM {AnalysisReport} r'
        ' LEFT JOIN ({HAS_ANALYSIS_REPORT} h JOIN {Project} pr'
        ' ON pr.gid = h.s) ON h.t = r.gid' + _PROJECT_EDGE_ORG,
    ),
    _source(
        'analysis_results',
        'WP2.8',
        "SELECT o.p->'id' AS organization_id, rep.p->'id' AS report_id,"
        " res.p->'slug' AS slug, res.p->'title' AS title,"
        " res.p->'description' AS description,"
        " res.p->'status' AS result_status,"
        " res.p->'plugin_slug' AS plugin_slug,"
        " res.p->'plugin_id' AS integration_id,"
        " NULLIF(res.p->'remediation', to_jsonb(''::text)) AS remediation,"
        " coalesce(rep.p->>'id', res.p->>'report_id', '?') || '/'"
        " || coalesce(res.p->>'plugin_id', '') || '/'"
        " || coalesce(res.p->>'slug', '') AS _src FROM {AnalysisResult} res"
        ' LEFT JOIN ({HAS_RESULT} hr JOIN {AnalysisReport} rep'
        ' ON rep.gid = hr.s) ON hr.t = res.gid'
        ' LEFT JOIN ({HAS_ANALYSIS_REPORT} h JOIN {Project} pr'
        ' ON pr.gid = h.s) ON h.t = rep.gid' + _PROJECT_EDGE_ORG,
    ),
    _source(
        'blueprints',
        'WP2.2',
        f"SELECT b.p->'id' AS id, {ONE_ORG} AS organization_id,"
        " b.p->'name' AS name, b.p->'slug' AS slug,"
        " b.p->'description' AS description, b.p->'icon' AS icon,"
        " b.p->'kind' AS kind, b.p->'type' AS entity_type,"
        " b.p->'source' AS source_type, b.p->'target' AS target_type,"
        " b.p->'edge' AS edge_type, b.p->'enabled' AS enabled,"
        " b.p->'priority' AS priority, b.p->'filter' AS filter,"
        " b.p->'json_schema' AS json_schema, b.p->'version' AS version,"
        " b.p->'created_at' AS created_at, b.p->'updated_at' AS updated_at,"
        " b.p->>'id' AS _src FROM {Blueprint} b",
    ),
    _source(
        'scoring_policies',
        'WP2.2',
        f"SELECT sp.p->'id' AS id, {ONE_ORG} AS organization_id,"
        " sp.p->'name' AS name, sp.p->'slug' AS slug,"
        " sp.p->'description' AS description,"
        " sp.p->'category' AS category, sp.p->'weight' AS weight,"
        " sp.p->'enabled' AS enabled, sp.p->'priority' AS priority,"
        ' (SELECT coalesce(jsonb_object_agg(kv.key, CASE WHEN kv.key IN ('
        + _SCORING_MAPS
        + ') THEN '
        + _decoded('kv.value')
        + " ELSE kv.value END), '{{}}'::jsonb)"
        " FROM jsonb_each(sp.p - ARRAY['id', 'name', 'slug', 'description',"
        " 'category', 'weight', 'enabled', 'priority', 'created_at',"
        " 'updated_at']::text[]) kv) AS parameters,"
        " sp.p->'created_at' AS created_at, sp.p->'updated_at' AS updated_at,"
        " sp.p->>'id' AS _src FROM {ScoringPolicy} sp",
    ),
    _source(
        'scoring_policy_targets',
        'WP2.2',
        f'SELECT {ONE_ORG} AS organization_id,'
        " sp.p->'id' AS scoring_policy_id, pt.p->'id' AS project_type_id,"
        " (sp.p->>'id') || '/' || (pt.p->>'id') AS _src"
        ' FROM {TARGETS} tg JOIN {ScoringPolicy} sp ON sp.gid = tg.s'
        ' JOIN {ProjectType} pt ON pt.gid = tg.t',
    ),
]

#: ``_src`` of a vertex ``v``: its ``id``, or its graph id when the node
#: has no ``id`` property (seeded nodes, plan WP1.9 research).
_SRC = "coalesce(v.p->>'id', 'gid:' || v.gid::text) AS _src"


def _attributes(keys: str) -> str:
    """The properties of ``v`` that are not in *keys*: blueprint values."""
    return f'(v.p - ARRAY[{keys}]::text[]) AS attributes'


def _revoked_at() -> str:
    """E10: the timestamp wins; a revoked node with no timestamp gets
    ``updated_at``, else ``created_at``."""
    return (
        "CASE WHEN nullif(v.p->'revoked_at', 'null'::jsonb) IS NOT NULL"
        " THEN v.p->'revoked_at' WHEN v.p->'revoked' = 'true'::jsonb"
        " THEN coalesce(nullif(v.p->'updated_at', 'null'::jsonb),"
        " v.p->'created_at') END AS revoked_at"
    )


_NODE = (
    "v.p->'id' AS id, v.p->'name' AS name, v.p->'slug' AS slug,"
    " v.p->'description' AS description, v.p->'icon' AS icon,"
)
_TIMES = " v.p->'created_at' AS created_at, v.p->'updated_at' AS updated_at,"
_NODE_KEYS = (
    "'id', 'name', 'slug', 'description', 'icon', 'created_at', 'updated_at'"
)

#: The owner of a credential ``v`` by its OWNED_BY edge.
_OWNER = (
    ' LEFT JOIN LATERAL (SELECT x.p AS p FROM {OWNED_BY} ob'
    ' JOIN (SELECT gid, p FROM {User} UNION ALL'
    ' SELECT gid, p FROM {ServiceAccount}) x ON x.gid = ob.t'
    ' WHERE ob.s = v.gid ORDER BY ob.gid DESC LIMIT 1) owner ON true'
)

IDENTITY: list[checks.Source] = [
    _source(
        'organizations',
        'WP2.1',
        'SELECT ' + _NODE + " v.p->'previous_slugs' AS previous_slugs,"
        " v.p->'tag_formats' AS tag_formats,"
        " v.p->'document_analytics_identities'"
        ' AS document_analytics_identities, '
        + _attributes(
            _NODE_KEYS + ", 'previous_slugs', 'tag_formats',"
            " 'document_analytics_identities'"
        )
        + ','
        + _TIMES
        + ' '
        + _SRC
        + ' FROM {Organization} v',
    ),
    _source(
        'teams',
        'WP2.1',
        "SELECT o.p->'id' AS organization_id, "
        + _NODE
        + _attributes(_NODE_KEYS)
        + ','
        + _TIMES
        + ' '
        + _SRC
        + ' FROM {Team} v'
        + BELONGS_TO_ORG,
    ),
    _source(
        'environments',
        'WP2.1',
        "SELECT o.p->'id' AS organization_id, "
        + _NODE
        + " v.p->'sort_order' AS sort_order,"
        " v.p->'label_color' AS label_color,"
        " v.p->'can_deploy' AS can_deploy,"
        " v.p->'can_promote' AS can_promote, v.p->'terminal' AS terminal,"
        " v.p->'allow_autonomous' AS allow_autonomous, "
        + _attributes(
            _NODE_KEYS + ", 'sort_order', 'label_color', 'can_deploy',"
            " 'can_promote', 'terminal', 'allow_autonomous'"
        )
        + ','
        + _TIMES
        + ' '
        + _SRC
        + ' FROM {Environment} v'
        + BELONGS_TO_ORG,
    ),
    _source(
        'project_types',
        'WP2.1',
        "SELECT o.p->'id' AS organization_id, "
        + _NODE
        + " v.p->'deployable' AS deployable,"
        " v.p->'releasable' AS releasable,"
        " v.p->'tag_formats' AS tag_formats, "
        + _attributes(
            _NODE_KEYS + ", 'deployable', 'releasable', 'tag_formats'"
        )
        + ','
        + _TIMES
        + ' '
        + _SRC
        + ' FROM {ProjectType} v'
        + BELONGS_TO_ORG,
    ),
    _source(
        'link_definitions',
        'WP2.1',
        "SELECT o.p->'id' AS organization_id, "
        + _NODE
        + " v.p->'url_template' AS url_template,"
        + _TIMES
        + ' '
        + _SRC
        + ' FROM {LinkDefinition} v'
        + BELONGS_TO_ORG,
    ),
    _source(
        'tags',
        'WP1.5',
        "SELECT o.p->'id' AS organization_id, v.p->'id' AS id,"
        " v.p->'name' AS name, v.p->'slug' AS slug,"
        " v.p->'description' AS description,"
        + _TIMES
        + ' '
        + _SRC
        + ' FROM {Tag} v'
        + BELONGS_TO_ORG,
    ),
    _source(
        'principals',
        'WP2.1',
        "SELECT v.p->'id' AS id, to_jsonb('user'::text) AS principal_type,"
        " v.p->'created_at' AS created_at, " + _SRC + ' FROM {User} v'
        " UNION ALL SELECT v.p->'id', to_jsonb('service_account'::text),"
        " v.p->'created_at', coalesce(v.p->>'id', 'gid:' || v.gid::text)"
        ' FROM {ServiceAccount} v',
    ),
    _source(
        'users',
        'WP2.1',
        "SELECT v.p->'id' AS id, to_jsonb('user'::text) AS principal_type,"
        " v.p->'email' AS email, v.p->'display_name' AS display_name,"
        " v.p->'password_hash' AS password_hash,"
        " v.p->'is_active' AS is_active, v.p->'is_admin' AS is_admin,"
        " v.p->'email_notifications' AS email_notifications,"
        " v.p->'avatar_url' AS avatar_url,"
        " v.p->'last_login' AS last_login_at,"
        + _TIMES
        + ' '
        + _SRC
        + ' FROM {User} v',
    ),
    _source(
        'service_accounts',
        'WP2.1',
        "SELECT v.p->'id' AS id,"
        " to_jsonb('service_account'::text) AS principal_type,"
        " v.p->'slug' AS slug, v.p->'display_name' AS display_name,"
        " v.p->'description' AS description, v.p->'is_active' AS is_active,"
        " v.p->'avatar_url' AS avatar_url,"
        " v.p->'last_authenticated' AS last_authenticated_at,"
        + _TIMES
        + ' '
        + _SRC
        + ' FROM {ServiceAccount} v',
    ),
    _source(
        'memberships',
        'WP2.1',
        "SELECT o.p->'id' AS organization_id, v.p->'id' AS principal_id,"
        " coalesce((SELECT r.p->'id' FROM {Role} r"
        " WHERE r.p->>'slug' = m.p->>'role' ORDER BY r.p->>'id' LIMIT 1),"
        " (SELECT r.p->'id' FROM {Role} r WHERE r.p->>'slug' = 'readonly'"
        " ORDER BY r.p->>'id' LIMIT 1)) AS role_id,"
        " coalesce(v.p->>'id', 'gid:' || v.gid::text) || '/'"
        " || coalesce(o.p->>'id', 'gid:' || o.gid::text) AS _src"
        ' FROM {MEMBER_OF} m JOIN {Organization} o ON o.gid = m.t'
        ' JOIN (SELECT gid, p FROM {User} UNION ALL'
        ' SELECT gid, p FROM {ServiceAccount}) v ON v.gid = m.s',
    ),
    _source(
        'team_members',
        'WP2.1',
        "SELECT o.p->'id' AS organization_id, t.p->'id' AS team_id,"
        " v.p->'id' AS user_id,"
        " (v.p->>'id') || '/' || (t.p->>'id') AS _src"
        ' FROM {MEMBER_OF} m JOIN {Team} t ON t.gid = m.t'
        ' JOIN {User} v ON v.gid = m.s'
        ' LEFT JOIN ({BELONGS_TO} bo JOIN {Organization} o ON o.gid = bo.t)'
        ' ON bo.s = t.gid',
    ),
    _source(
        'roles',
        'WP2.1',
        f'SELECT {ONE_ORG} AS organization_id, '
        + _NODE
        + " parent.p->'id' AS parent_role_id, v.p->'priority' AS priority,"
        " v.p->'is_system' AS is_system, v.p->'is_default' AS is_default,"
        + _TIMES
        + ' '
        + _SRC
        + ' FROM {Role} v'
        ' LEFT JOIN LATERAL (SELECT r.p FROM {INHERITS_FROM} i'
        ' JOIN {Role} r ON r.gid = i.t WHERE i.s = v.gid'
        ' ORDER BY i.gid DESC LIMIT 1) parent ON true',
    ),
    _source(
        'role_grants',
        'WP2.3',
        f"SELECT {ONE_ORG} AS organization_id, v.p->'id' AS role_id,"
        " perm.p->'name' AS permission_name,"
        " coalesce(v.p->>'id', 'gid:' || v.gid::text) || '/'"
        " || coalesce(perm.p->>'name', '?') AS _src"
        ' FROM {GRANTS} g JOIN {Role} v ON v.gid = g.s'
        ' JOIN {Permission} perm ON perm.gid = g.t',
    ),
    _source(
        'permissions',
        'WP2.3',
        "SELECT v.p->'name' AS name, v.p->'resource_type' AS resource_type,"
        " v.p->'action' AS action, v.p->'description' AS description,"
        " coalesce(v.p->>'name', 'gid:' || v.gid::text) AS _src"
        ' FROM {Permission} v',
    ),
    _source(
        'issued_tokens',
        'WP2.3',
        "SELECT owner.p->'id' AS principal_id, v.p->'jti' AS jti,"
        " v.p->'token_type' AS token_type, v.p->'family_id' AS family_id,"
        " v.p->'issued_at' AS issued_at, v.p->'expires_at' AS expires_at, "
        + _revoked_at()
        + ", v.p->'created_at' AS created_at,"
        " coalesce(v.p->>'jti', 'gid:' || v.gid::text) AS _src"
        ' FROM {TokenMetadata} v'
        ' LEFT JOIN LATERAL (SELECT x.p AS p FROM {ISSUED_TO} it'
        ' JOIN (SELECT gid, p FROM {User} UNION ALL'
        ' SELECT gid, p FROM {ServiceAccount}) x ON x.gid = it.t'
        ' WHERE it.s = v.gid ORDER BY it.gid DESC LIMIT 1) owner ON true',
    ),
    _source(
        'totp_secrets',
        'WP2.3',
        "SELECT u.p->'id' AS user_id, v.p->'secret' AS secret_encrypted,"
        " v.p->'enabled' AS enabled,"
        " v.p->'backup_codes' AS backup_code_hashes,"
        " v.p->'last_used' AS last_used_at,"
        + _TIMES
        + ' '
        + _SRC
        + ' FROM {TOTPSecret} v'
        ' LEFT JOIN ({MFA_FOR} mf JOIN {User} u ON u.gid = mf.t)'
        ' ON mf.s = v.gid',
    ),
    _source(
        'api_keys',
        'WP2.3',
        "SELECT v.p->'id' AS id, owner.p->'id' AS principal_id,"
        " v.p->'key_id' AS key_id, v.p->'key_hash' AS key_hash,"
        " v.p->'name' AS name, v.p->'description' AS description,"
        " v.p->'scopes' AS scopes, v.p->'expires_at' AS expires_at,"
        " v.p->'last_used' AS last_used_at,"
        " v.p->'last_rotated' AS last_rotated_at, "
        + _revoked_at()
        + ','
        + _TIMES
        + ' '
        + _SRC
        + ' FROM {APIKey} v'
        + _OWNER,
    ),
    _source(
        'client_credentials',
        'WP2.3',
        "SELECT v.p->'id' AS id, owner.p->'id' AS service_account_id,"
        " v.p->'client_id' AS client_id,"
        " v.p->'client_secret_hash' AS client_secret_hash,"
        " v.p->'name' AS name, v.p->'description' AS description,"
        " v.p->'scopes' AS scopes, v.p->'expires_at' AS expires_at,"
        " v.p->'last_used' AS last_used_at,"
        " v.p->'last_rotated' AS last_rotated_at, "
        + _revoked_at()
        + ','
        + _TIMES
        + ' '
        + _SRC
        + ' FROM {ClientCredential} v'
        + _OWNER,
    ),
    _source(
        'oauth_clients',
        'WP2.3',
        "SELECT v.p->'id' AS id, v.p->'client_id' AS client_id,"
        " v.p->'client_name' AS client_name,"
        " v.p->'redirect_uris' AS redirect_uris,"
        " v.p->'grant_types' AS grant_types,"
        " v.p->'response_types' AS response_types,"
        " v.p->'token_endpoint_auth_method' AS token_endpoint_auth_method,"
        " v.p->'scope' AS scope,"
        + _TIMES
        + ' '
        + _SRC
        + ' FROM {OAuthClient} v',
    ),
    _source(
        'identity_connections',
        'WP2.3',
        "SELECT v.p->'id' AS id, v.p->'integration_id' AS integration_id,"
        " (SELECT o.p->'id' FROM {Integration} i JOIN {BELONGS_TO} b"
        ' ON b.s = i.gid JOIN {Organization} o ON o.gid = b.t'
        " WHERE i.p->'id' = v.p->'integration_id' LIMIT 1)"
        ' AS organization_id,'
        " v.p->'user_id' AS user_id, v.p->'subject' AS subject,"
        " v.p->'access_token_encrypted' AS access_token_encrypted,"
        " v.p->'refresh_token_encrypted' AS refresh_token_encrypted,"
        " v.p->'id_token_claims_encrypted' AS id_token_claims_encrypted,"
        " v.p->'scopes' AS scopes, v.p->'status' AS connection_status,"
        " v.p->'expires_at' AS expires_at,"
        " v.p->'last_used_at' AS last_used_at,"
        " v.p->'metadata' AS metadata,"
        + _TIMES
        + ' '
        + _SRC
        + ' FROM {IdentityConnection} v',
    ),
    _source(
        'password_reset_tokens',
        'WP2.3',
        "SELECT v.p->'id' AS id, (SELECT u.p->'id' FROM {User} u"
        " WHERE u.p->>'email' = v.p->>'email' ORDER BY u.p->>'id' LIMIT 1)"
        " AS user_id, v.p->'token' AS token_hash,"
        " v.p->'expires_at' AS expires_at, v.p->'used_at' AS used_at,"
        " v.p->'created_at' AS created_at, "
        + _SRC
        + ' FROM {PasswordResetToken} v',
    ),
    _source(
        'local_auth_settings',
        'WP2.3',
        "SELECT to_jsonb(true) AS singleton, v.p->'enabled' AS enabled,"
        " v.p->'updated_at' AS updated_at, "
        + _SRC
        + ' FROM {LocalAuthConfig} v',
    ),
]

SOURCES: list[checks.Source] = [
    *IDENTITY,
    *DELIVERY,
    *CONTENT,
    *INTEGRATIONS,
]

#: The tables with no source query, and why.
NOT_COVERED: dict[str, str] = {
    'tenants': 'no graph source: the ETL creates one row (E2)',
    'component_overrides': 'no graph source: a new table',
    'component_release_overrides': 'no graph source: a new table',
    'plugin_entity_keys': (
        'no graph source: the ETL derives the rows from the plugin manifests'
    ),
    'embeddings': 'E28, E29, and E32 check the legacy public.embeddings',
    'resource_acls': (
        'no code writes CAN_ACCESS; the ETL maps the target label to'
        ' resource_type'
    ),
}
