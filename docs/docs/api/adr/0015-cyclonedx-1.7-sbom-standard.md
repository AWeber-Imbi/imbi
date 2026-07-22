# ADR 0015: CycloneDX 1.7 as the SBoM Standard

## Status

Accepted

Date: 2026-05-27

Source design lives in [`plans/sbom-ingest.md`](https://github.com/AWeber-Imbi/imbi-development/blob/main/plans/sbom-ingest.md).

## Context

Imbi attributes third-party software usage to a project's `Release`
via the `Release -[:USES_COMPONENT_RELEASE]-> ComponentRelease` edge
(see `ReleaseComponentEdge` in
`imbi-common/src/imbi.common/models.py`). To populate that edge we
ingest Software Bills of Materials (SBoMs) produced by build CI and
push the resulting `Component` / `ComponentRelease` /
`ComponentIdentifier` nodes through a single
`PUT /organizations/{org}/projects/{project_id}/releases/{release_id}/sbom`
endpoint.

Two questions had to be settled before the ingest pipeline could be
written:

1. **Which SBoM spec version do we accept on the wire?** CycloneDX
   1.5, 1.6, and 1.7 are all in the wild. Each release strictly
   expanded the schema; 1.7 added fields Imbi reads (notably
   per-component properties used to carry dependency-group attribution
   in the cdxgen output). Accepting earlier versions would silently
   drop those fields on the floor.
2. **Which producer do we recommend in build CI?** Imbi's normalizer
   only sees what the producer emitted. We need a single tool that
   covers our polyglot service population (uv-based Python, npm /
   yarn / pnpm JS / TS, Maven / Gradle Java, Go) and that emits the
   per-component metadata required to populate `scope` and `groups`
   on `ReleaseComponentEdge`.

We evaluated `cyclonedx-py` (the `cyclonedx-bom` PyPI package) for
the Python side and found it does not handle PEP 735
`[dependency-groups]` at all — dev-vs-runtime attribution is simply
lost for `uv` and `pdm` projects. We also considered an ecosystem-
per-tool fleet (cyclonedx-py for Python, cyclonedx-npm for JS, the
Maven plugin for Java, etc.) but rejected it because each tool
encodes group / scope metadata in a different shape, which would
push ecosystem-specific knowledge into the Imbi normalizer. cdxgen
(<https://github.com/CycloneDX/cdxgen>) is the only common tool we
found that emits CycloneDX 1.7 with consistent, useful
per-component metadata across the languages we care about.

## Decision

### 1. CycloneDX 1.7 is the only spec version Imbi accepts

The ingest endpoint enforces `specVersion == "1.7"` and rejects
anything else with `415 Unsupported Media Type`. Implementation:

- `imbi-api/src/imbi.api/sbom.py` declares
  `SUPPORTED_SPEC_VERSION: typing.Final = '1.7'`.
- A version mismatch raises `UnsupportedSpecVersionError` from
  `parse()`, which the endpoint maps to HTTP 415.

We deliberately do not coerce 1.5 / 1.6 payloads up to 1.7. The
later schema introduced fields we depend on; silent up-conversion
would produce CycloneDX documents that look 1.7-shaped but are
missing data the normalizer expects.

### 2. cdxgen is the recommended producer

cdxgen (<https://github.com/CycloneDX/cdxgen>) is the SBoM producer
Imbi documents in service-onboarding guidance for build CI. It
covers the languages currently in the fleet from a single
invocation, and — critically — exposes per-component metadata that
Imbi reads to populate `ReleaseComponentEdge`:

- **`component.scope`** (`required` / `optional` / `excluded`) is
  defined by CycloneDX itself and is universal across ecosystems.
  Imbi stores it verbatim as `ReleaseComponentEdge.scope`, mapping
  `None` to "producer did not declare a scope."
- **`component.properties[].name == "cdx:pyproject:group"`** is
  cdxgen's encoding for both PEP 735 `[dependency-groups]` and
  Poetry `[tool.poetry.group.X]`. Imbi flattens these into
  `ReleaseComponentEdge.groups`, sorted and de-duplicated at ingest
  time so equality comparisons across releases are stable.

Python is currently the only ecosystem that emits named dependency
groups; the Imbi parser maintains a curated allow-list of property
names rather than ingesting every cdxgen property by default. As
cdxgen adds equivalent group support for other ecosystems (e.g. npm
`devDependencies` groups, Maven scopes-as-groups), the allow-list
grows — the consuming graph contract does not change.

### 3. `cyclonedx-python-lib` is the parser, not the producer

Imbi parses incoming SBoMs with the `cyclonedx-python-lib`
PyPI package, pinned `>=11.7,<12` in `imbi-api/pyproject.toml`.
This is an entirely separate concern from the producer choice:

- The library gives us a typed, validated CycloneDX 1.7 object
  graph to project into `NormalizedComponent` records.
- It runs server-side, on whatever payload the producer emitted.
  We could swap producers tomorrow and the parser would not move.

The two choices are recorded together in this ADR only because
they are easy to conflate in conversation; conflating them in
code (e.g., gating ingestion on `User-Agent: cdxgen/*`) would be
a mistake.

## Consequences

### Positive

- The producer side and consumer side share one schema version, so
  every field cdxgen emits maps onto a field Imbi understands. No
  silent data loss on dev-group attribution for Python.
- The Imbi normalizer stays ecosystem-agnostic. It reads
  `component.scope` and one curated set of property names; it does
  not branch on `purl` type to decide which fields exist.
- A single recommended producer simplifies onboarding docs and CI
  templates. Service teams get one `cdxgen … -o cyclonedx.json`
  invocation, not a per-language matrix.
- The parser is library-pinned and free to evolve independently of
  build CI; producer upgrades don't force coordinated API releases.

### Negative

- Build CI is on the hook for keeping cdxgen current. cdxgen is
  active upstream but not run by us; an upstream regression in
  group emission would degrade attribution quietly until someone
  noticed `groups` arrays going empty.
- Rejecting 1.5 / 1.6 means any team running an older cdxgen (or a
  different tool that only emits 1.6) gets a hard `415` instead of
  a partial ingest. This is intentional — partial ingest is the
  failure mode this ADR exists to avoid — but it does shift the
  fix-it work onto the producer side.
- We are tied to one producer's property naming convention
  (`cdx:pyproject:group`) for dependency-group attribution. If
  cdxgen renames or restructures the property, the Imbi
  normalizer's allow-list must move with it. That coupling is the
  price of ecosystem-agnostic ingest.

### Risks Accepted

- **Multi-version compatibility**: not a goal. We will not run a
  1.5 / 1.6 compatibility shim. Producers that cannot emit 1.7 are
  not supported producers.
- **Producer monoculture**: we are recommending a single tool. A
  team is free to emit CycloneDX 1.7 from a different producer
  (the parser does not care), but they lose dependency-group
  attribution unless that producer happens to emit the same
  property names. This is acceptable because the alternative —
  matrixing the normalizer over every producer's metadata
  convention — pushes ecosystem branching into core.
- **bom-ref persistence**: not done. CycloneDX `bom-ref` is a
  per-SBoM internal cross-reference, not a stable component
  identity, and the parser excludes it from `_IDENTIFIER_KINDS` in
  `imbi-api/src/imbi.api/sbom.py`. Anyone tempted to "just persist
  the bom-ref" should re-read the comment there before doing so.

## References

- [`plans/sbom-ingest.md`](https://github.com/AWeber-Imbi/imbi-development/blob/main/plans/sbom-ingest.md) — Full ingest plan, including the cdxgen evaluation and the curated property allow-list.
- `imbi-api/src/imbi.api/sbom.py` — `SUPPORTED_SPEC_VERSION`,
  `UnsupportedSpecVersionError`, and the parse / upsert pipeline.
- `imbi-common/src/imbi.common/models.py` — `Component`,
  `ComponentRelease`, `ComponentIdentifier`, and
  `ReleaseComponentEdge` (the graph contract this ADR populates).
- [CycloneDX 1.7 specification](https://cyclonedx.org/docs/1.7/json/)
- [cdxgen](https://github.com/CycloneDX/cdxgen) — recommended SBoM producer.
- [cyclonedx-python-lib](https://github.com/CycloneDX/cyclonedx-python-lib) — server-side parser.
