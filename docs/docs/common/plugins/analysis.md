# Analysis Plugins

`AnalysisPlugin` is the abstract base for plugins that inspect a project
and emit Project Doctor findings — `pass` / `warn` / `fail` items with a
markdown body. Declare `plugin_type='analysis'` in the manifest. The
host (`imbi-api`) resolves applicable analysis plugins for a project
through both the project-type `USES_PLUGIN` edge (`tab='analysis'`) and
via any `ThirdPartyService` the project `EXISTS_IN` that has a
`HAS_PLUGIN` edge to an analysis plugin.

See [Authoring Plugins](index.md) for the manifest, context, credential
resolution, and error conventions shared by every plugin.

## Contract

`AnalysisPlugin` has a single abstract method:

```python
from imbi_common.plugins import (
    AnalysisPlugin,
    AnalysisResultItem,
    PluginContext,
    PluginManifest,
)


class GitHubAnalysisPlugin(AnalysisPlugin):
    manifest = PluginManifest(
        slug='github-analysis',
        name='GitHub Analysis',
        plugin_type='analysis',
    )

    async def analyze(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> list[AnalysisResultItem]:
        return [
            AnalysisResultItem(
                slug='github:url-drift',
                title='Repository URL drift',
                description=(
                    'The configured `github-repository` link points at '
                    '`old/repo` but GitHub redirects to `new/repo`. '
                    'Update the link to clear this finding.'
                ),
                status='warn',
            )
        ]
```

Each `AnalysisResultItem` carries a stable per-plugin `slug` so the UI
and any matching `analysis_result` scoring policy can refer to the
finding across runs. The `description` is rendered as Markdown in the
Doctor panel.

## Remediating a finding

A finding is *fixable* when `analyze` attaches a `RemediationOffer` to
it. The Doctor panel renders a button labelled `offer.label`; clicking
it asks the host to call the emitting plugin's `remediate` with the
offer's `id`. Implement `remediate` whenever you emit an offer:

```python
from imbi_common.plugins import (
    RemediationOffer,
    RemediationResult,
    ServiceWriteback,
)


class GitHubAnalysisPlugin(AnalysisPlugin):
    ...

    async def analyze(self, ctx, credentials):
        return [
            AnalysisResultItem(
                slug='github:id-drift',
                title='Repository id drift',
                description='The stored identifier no longer matches GitHub.',
                status='fail',
                remediation=RemediationOffer(
                    id='id-drift',
                    label='Repair repository edge',
                ),
            )
        ]

    async def remediate(self, ctx, credentials, remediation_id):
        if remediation_id != 'id-drift':
            return await super().remediate(ctx, credentials, remediation_id)
        repo = await self._fetch_repo(ctx, credentials)
        # Re-verify before writing so the call is idempotent.
        conn = next(
            (c for c in ctx.service_connections
             if c.service_slug == ctx.third_party_service_slug),
            None,
        )
        if conn and conn.identifier == str(repo['id']):
            return RemediationResult(status='noop', message='Already correct.')
        # Plugins have no DB handle: effect the change via the write-back
        # channel, exactly as lifecycle plugins do. The host persists it.
        ctx.service_writeback = ServiceWriteback(
            identifier=str(repo['id']),
            canonical_url=f"{api_base}/repositories/{repo['id']}",
        )
        return RemediationResult(status='fixed', message='Repaired the edge.')
```

`remediate` must re-verify the discrepancy and return a `noop`
`RemediationResult` when the finding is already resolved, so a
double-click — or the bulk "fix all" pass — is safe. The default
implementation raises `PluginRemediationNotSupported`; only plugins
that emit offers need override it. Set `RemediationOffer.destructive`
for fixes that create/remove an edge or delete a value (the UI then
requires explicit confirmation).

## How findings reach the panel

The host fans the call out across every applicable analysis plugin (via
`asyncio.gather`), captures plugin exceptions as a synthetic
`fail` result, and persists the merged report on
`(:Project)-[:HAS_ANALYSIS_REPORT]->(:AnalysisReport)
-[:HAS_RESULT]->(:AnalysisResult)`. Only the latest report is retained
— re-running analysis replaces the previous one.

The `AnalysisReport.overall_status` is the worst observed result; the
project page colour-codes the Doctor icon from it.

## Feeding the score

A scoring policy of category `analysis_result` references an
`AnalysisResult.slug` (the same slug your plugin emits) and maps its
`status` to a 0-100 score via `status_score_map`
(defaults: `{'pass': 100, 'warn': 50, 'fail': 0}`). When the project's
latest report contains a matching result the policy contributes to the
Health & Compliance score; missing results contribute `None`, matching
the convention every other category uses for missing data.

## Reference

::: imbi_common.plugins.AnalysisPlugin

::: imbi_common.plugins.AnalysisResultItem

::: imbi_common.plugins.AnalysisResultStatus

::: imbi_common.plugins.RemediationOffer

::: imbi_common.plugins.RemediationResult
