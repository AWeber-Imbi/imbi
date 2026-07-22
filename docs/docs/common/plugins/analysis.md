# Analysis Capability

`AnalysisCapability` is the contract base for a capability that inspects
a project and emits Project Doctor findings — `pass` / `warn` / `fail`
items with a markdown body. Bind it with a
`Capability(kind='analysis', handler=...)` in the plugin's manifest. The
host (`imbi-api`) resolves applicable analysis capabilities for a project
through the project-type `USES` assignment and via any Integration the
project `EXISTS_IN` whose plugin declares an analysis capability.

Surfaces: **ui, api**.

See [Authoring Plugins](index.md) for the manifest, capabilities,
context, credential decryption, and error conventions shared by every
plugin.

## Contract

`AnalysisCapability` has a single abstract method, `analyze`:

```python
from imbi.common.plugins import (
    AnalysisCapability,
    AnalysisResultItem,
    PluginContext,
)


class GitHubAnalysis(AnalysisCapability):
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

Each `AnalysisResultItem` carries a stable per-capability `slug` so the
UI and any matching `analysis_result` scoring policy can refer to the
finding across runs. The `description` is rendered as Markdown in the
Doctor panel.

## Remediating a finding

A finding is *fixable* when `analyze` attaches a `RemediationOffer` to
it. The Doctor panel renders a button labelled `offer.label`; clicking it
asks the host to call the emitting capability's `remediate` with the
offer's `id`. Implement `remediate` whenever you emit an offer:

```python
from imbi.common.plugins import (
    AnalysisResultItem,
    RemediationOffer,
    RemediationResult,
    ServiceWriteback,
)


class GitHubAnalysis(AnalysisCapability):
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
             if c.integration_slug == ctx.integration_slug),
            None,
        )
        if conn and conn.identifier == str(repo['id']):
            return RemediationResult(status='noop', message='Already correct.')
        # Capabilities have no DB handle: effect the change via the
        # write-back channel, exactly as lifecycle capabilities do.
        ctx.service_writeback = ServiceWriteback(
            identifier=str(repo['id']),
            canonical_url=f"{api_base}/repositories/{repo['id']}",
        )
        return RemediationResult(status='fixed', message='Repaired the edge.')
```

`remediate` must re-verify the discrepancy and return a `noop`
`RemediationResult` when the finding is already resolved, so a
double-click — or the bulk "fix all" pass — is safe. The default
implementation raises `PluginRemediationNotSupported`; only capabilities
that emit offers need override it. Set `RemediationOffer.destructive`
for fixes that create/remove an edge or delete a value (the UI then
requires explicit confirmation).

## How findings reach the panel

The host fans the call out across every applicable analysis capability
(via `asyncio.gather`), captures exceptions as a synthetic `fail`
result, and persists the merged report on
`(:Project)-[:HAS_ANALYSIS_REPORT]->(:AnalysisReport)
-[:HAS_RESULT]->(:AnalysisResult)`. Only the latest report is retained —
re-running analysis replaces the previous one.

The `AnalysisReport.overall_status` is the worst observed result; the
project page colour-codes the Doctor icon from it.

## Feeding the score

A scoring policy of category `analysis_result` references an
`AnalysisResult.slug` (the same slug your capability emits) and maps its
`status` to a 0-100 score via `status_score_map`
(defaults: `{'pass': 100, 'warn': 50, 'fail': 0}`). When the project's
latest report contains a matching result the policy contributes to the
Health & Compliance score; missing results contribute `None`.

## Hints

- **`cacheable`** — the host may cache reads from this capability.

## API reference

::: imbi.common.plugins.AnalysisCapability

::: imbi.common.plugins.AnalysisResultItem

::: imbi.common.plugins.AnalysisResultStatus

::: imbi.common.plugins.RemediationOffer

::: imbi.common.plugins.RemediationResult
