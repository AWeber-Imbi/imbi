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
