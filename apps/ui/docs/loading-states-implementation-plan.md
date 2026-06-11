# Loading States — Implementation Plan

Source pattern: `docs/loading-patterns.html` ("Loading states" engineering pattern).
Audit date: 2026-06-10. Scope: every surface in `src/` that fetches on mount or navigation.

## What the pattern requires

1. **Skeletons, never spinners or labels.** Every region that fetches on mount/navigation
   replaces itself with a skeleton built to the same footprint as the real content
   (same rows, widths, radii). No blank panels, no centered spinners, no "Loading…" text.
2. **Sweep animation**, not pulse: `.sk` block with a low-contrast gradient sweep
   (`sk-sweep` keyframes, 1.5s), warm-gray base that stays visible under reduced motion.
3. **Reveal in waves.** Each region resolves independently as its own request lands
   (`.reveal` fade+lift, staggered `delay={i * 50}` when several arrive together).
   Never gate a page on its slowest query.
4. **Amber AI variant** (`sk-ai`) + "thinking" header for Imbot-generated content only;
   resolves into streaming text; dependent actions disabled until done.
5. **Accessibility & honesty:** `aria-busy="true"` on loading regions (cleared on data),
   skeletons `aria-hidden`, sweep/reveal disabled under `prefers-reduced-motion`,
   no fake progress.
6. **Out of scope by design:** instant local state (filtering a loaded list) and
   action-in-flight button busy states (saving, deploying) — those stay button spinners.

## Current state — infrastructure gap

| Doc requires | Exists today | Gap |
|---|---|---|
| `.sk` sweep skeleton CSS | `Skeleton` (`ui/skeleton.tsx`) using Tailwind `animate-pulse`, `bg-tertiary/30` | Wrong animation (pulse vs sweep); no warm-gray token; no dark-theme variant per spec |
| `sk-ai` amber variant | nothing | Missing entirely |
| `.reveal` fade+lift | nothing | Missing entirely |
| `Sk` / `SkText` / `Swap` helpers | `Skeleton` only | No text-paragraph helper, no swap/reveal wrapper, no stagger support |
| `aria-busy` convention | 6 call sites (deploy/, OperationsLog) | Not systematic; `LoadingState` and most skeletons lack it |
| `prefers-reduced-motion` CSS | one JS check in OperationsLog scroll | No CSS media query anywhere; `animate-pulse`/`animate-spin`/`imbi-pulse` never disabled |
| — (forbidden) | `LoadingState` (`ui/loading-state.tsx`): centered text label, used by ~21 files + `AdminSection` | Explicitly forbidden pattern; must be removed |
| — (forbidden) | `PageFallback` (`App.tsx:174`): full-screen centered "Loading…" for all 10 lazy routes | Forbidden pattern at the route level |

There are **zero** fully conforming surfaces today. The closest are `deploy/lists.tsx`
(skeleton rows + `aria-busy`, but static blocks, not footprint-matched, no sweep/reveal)
and the dashboard widgets (generic `Skeleton` blocks approximating row heights).

## Inventory of data-loading surfaces

Classification legend:
- **skeleton-generic** — skeleton blocks present but not footprint-matched, pulse not sweep, no reveal
- **text-loading** — `LoadingState` or literal "Loading…" text (forbidden)
- **spinner** — region-level spinner (forbidden; button/toast spinners are fine)
- **none** — renders null/blank while loading, or risks flashing the empty state
- Flags: ⛔ blocks region/page on slowest of several queries · ⚠️ empty-state flash risk

### Shared infrastructure (fixing these fixes many pages at once)

| Surface | Today | Notes |
|---|---|---|
| `ui/skeleton.tsx` `Skeleton` | pulse animation | Becomes the `Sk` primitive: sweep + `ai` variant + `aria-hidden` |
| `ui/loading-state.tsx` `LoadingState` | centered text | Delete after migration (21 consumers) |
| `admin/AdminSection.tsx` | `if (isLoading) return <LoadingState/>` (line 49) | Gates ~17 admin list pages; replace with header+search+table skeleton |
| `ui/admin-table.tsx` `AdminTable` | no loading affordance; `emptyMessage` when `rows=[]` | Add skeleton-row mode mirroring column layout |
| `App.tsx` `PageFallback` | full-screen "Loading…" text | App-shell skeleton (nav rail + content blocks) for all 10 lazy routes + BootstrapGate |
| `hooks/useAdminCrud.ts` | exposes `isLoading` (list query only) | API fine; consumers change |

### Core pages

| Surface | Today | Flags |
|---|---|---|
| `pages/ProjectDetailPage.tsx` | text-loading ("Loading project...", centered) | ⛔ blocks whole page on project fetch |
| `components/ProjectDetail.tsx` | none — 11+ queries; tab regions render blank until data | ⚠️ per-region; overview gates score trend + breakdown together |
| `components/ProjectsView.tsx` | text-loading ("Loading projects...", centered h-64) | ⛔ |
| `components/Dashboard.tsx` + `dashboard/widgets/*` | skeleton-generic (StatWidget h-8 w-20; RecentDeployments 4×h-16; MyPullRequests 4×h-20; some widgets have `role="status"`/aria-label) | Closest to target; needs footprint match + sweep + reveal |
| `components/OperationsLog.tsx` | text-loading (`LoadingState "Loading operations log…"`); page-level `aria-busy`+`inert`+opacity overlay; "Loading more…" text for next page | ⛔ metadata queries (projects/envs/users) gate page |
| `components/CommandBar.tsx` (search) | spinner + "Searching…" pulsing text in SearchResultsPanel | |
| `contexts/OrganizationContext.tsx` | none (consumers check isLoading ad hoc) | |

### Project detail tabs

| Surface | Today | Flags |
|---|---|---|
| `deployments/DeploymentsTab.tsx` | text-loading | ⛔ 3 queries (current releases, history, commits) gate whole tab |
| `releases/ReleasesTab.tsx` | text-loading ("Loading releases…") | ⛔ 2 queries (drift, history) |
| `dependencies/DependenciesTab.tsx` | text-loading | ⛔ sequential gating (releases → dependencies) |
| `documents/ProjectDocumentsTab.tsx` | text-loading | |
| `project/ConfigurationTab.tsx` | text-loading (left panel) | ⛔ 6+ per-env queries |
| `project/IncidentsTab.tsx` | text-loading | |
| `project/LogsTab.tsx` | text-loading | |
| `project/ProjectPullRequestsTab.tsx` | skeleton-generic (5 rows, single block per row — real rows have icon/title/badge/avatar/diff columns) | |
| `project/ProjectPluginsSection.tsx` | none (queries silent) | ⚠️ |
| `components/ProjectRelationshipsTab.tsx` | text-loading ("Loading relationships…") | ⚠️ sub-sections check `length === 0` unguarded |
| `components/ScoreHistoryTab.tsx` | text-loading | ⚠️⚠️ chart + event timeline render "No data for this period" with no isLoading guard (worst flash risk in app) |
| `components/ProjectDoctorTab.tsx` | text-loading / empty until report arrives | ⚠️ |
| `components/ProjectActivityLog.tsx` | spinner (LoaderCircle + "Loading activity…") | |
| `components/IntegrationsCard.tsx` | none | ⚠️ |
| `deploy/DeployTab.tsx` | skeleton-generic + `aria-busy` (best in app) | needs footprint + sweep + reveal |
| `deploy/lists.tsx` (BranchList/CommitList/TagList) | skeleton-generic + `aria-busy` + aria-labels | single wide block per row vs multi-column real rows |
| `deploy/PromoteTab.tsx` | text-loading ("Loading commits…") | |
| `deployments/EnvironmentNav.tsx` | spinner (Loader2 size-13) | |

### Admin area

| Surface | Today | Flags |
|---|---|---|
| 17 `*Management.tsx` list pages (Role, User, Team, Organization, Environment, ProjectType, ScoringPolicy, ServiceAccount, LinkDefinition, DocumentTemplate, Blueprint, Webhook, ThirdPartyService, Assistant…) | text-loading via `AdminSection` | Fixed wholesale by AdminSection/AdminTable |
| `AdminOverview.tsx` (MetricTile, DeploysByEnv, ProjectHealth, SystemHealthRail) | skeleton-generic | ⛔ some tiles gate multiple queries |
| `PluginsManagement.tsx` / `PluginPackageDetail.tsx` / `PluginEntityManagement.tsx` | text-loading | ⛔ serial queries |
| `AuthProvidersManagement.tsx` | text-loading | ⛔ 2 queries |
| Detail views: `RoleDetail`, `UserDetail`, `TeamDetail`, `OrganizationDetail`, `EnvironmentDetail`, `WebhookDetail`, `ThirdPartyServiceDetail`, `BlueprintDetail` | text-loading or none | RoleDetail runs 5 queries |
| `AnchorEdgesCard.tsx` | none | ⚠️ shows "Not mapped to any…" while loading |
| `ServiceAccountForm` (edit-mode fetch) | none | |
| `graph-query/ResultCard.tsx` (lazy ResultGraph) | spinner Suspense fallback | |

### Other surfaces

| Surface | Today | Flags |
|---|---|---|
| `settings/SettingsConnections.tsx` | text-loading | ⛔ plugins + identities gated together |
| `settings/SettingsApiKeys.tsx` | text-loading (`<p>Loading...</p>`) | |
| `reports/TeamKPIReport.tsx` | text-loading | ⛔ rollup + teams |
| `reports/*` (OpenPullRequestsReport, ScoreHistoryReport, MonthlyImprovementReport, ProjectsGraphReport) | mixed spinner/text — audit each during phase 4 | |
| `pages/UserProfile/UserProfilePage.tsx` + ContributionHeatmap, RecentActivity | text-loading | ⛔ 4 parallel queries |
| `components/RecentActivity.tsx` (+ RecentActivityWidget) | text-loading; "Loading more…" button text | |
| `operations-log/OperationsLogSummary.tsx` | skeleton-generic (good) | |
| Dialogs: `NewProjectDialog`, `NewOpsLogDialog`, `EditRelationshipsDialog` | none/blank or spinner while `enabled: isOpen` queries run | ⚠️ form fields appear empty then populate |
| `ProjectGraphView.tsx` / `LazyProjectsGraphCanvas.tsx` | spinner Suspense fallback + render spinner | |
| `documents/comments/LazyRichComposer.tsx` | "Loading editor…" text Suspense fallback | |

### AI (Imbot) surfaces — amber variant required

| Surface | Today | Gap vs pattern |
|---|---|---|
| `CommandBar.tsx` assistant (SSE via `api/assistant.ts` + Zustand store) | Streaming ✓, ToolUseIndicator spinner + friendly text ✓, input disabled while streaming ✓ | No amber skeleton, no "Imbot is reading…" thinking header; tool results pop in |
| `deployments/PendingPromoteCard.tsx` (draft release notes) | button spinner during mutation | AI-generated value: needs amber skeleton + thinking header where notes render; gate the promote action until done |
| `releases/ReleaseReadyCard.tsx` (AI draft) | button spinner during mutation | Same: amber skeleton + gate "Cut release" |

### Correct as-is (no change)

- All 33 audited button/toast spinners for mutations (deploy, promote, save, upload,
  connection test, rescore…) — action-in-flight states are explicitly allowed.
- Refetch-icon spins on `isFetching` (ProjectsView refresh, IncidentsTab, LogsTab) —
  background refresh, not initial load.
- Presentational children fed by props (cards under DeploymentsTab, ReleaseHistory,
  AdminTable rows, UserProfile sub-cards) — their parents own the loading state.
- `MessageBubble` streaming text rendering.

## Implementation plan

Ordered so each phase ships independently; Phase 0–1 deliver the most visible change
for the least code.

### Phase 0 — Infrastructure (everything else depends on this)

- [ ] Add skeleton CSS to `src/index.css` per the doc: `.sk` base + `::after` sweep
      (`sk-sweep` 1.5s), `.sk-ai` amber variant, `.sk-line`, `.dark` overrides,
      `.reveal` keyframes, and the `prefers-reduced-motion` block (sweep off,
      reveal off, base stays visible). Map the doc's hex values onto the existing
      Tailwind v4 `@theme` tokens where they exist (amber from the brand palette).
- [ ] Rework `ui/skeleton.tsx` into the doc's helpers, keeping the `Skeleton` export
      working during migration: `Sk` (w/h/r/ai/line/circle props, `aria-hidden`),
      `SkText` (widths array), `Swap` (`ready`/`skeleton`/`delay`, applies `.reveal`).
- [ ] Establish the `aria-busy` convention: the region container (not the skeleton)
      carries `aria-busy={!ready}`; bake it into `Swap`'s wrapper so call sites get
      it for free.
- [ ] Add a global `@media (prefers-reduced-motion: reduce)` block covering the
      existing `imbi-pulse`, `imbi-pulse-ring`, `imbi-bridge-travel` keyframes too
      (currently never disabled — independent a11y bug surfaced by this audit).
- [ ] Document the pattern in `CLAUDE.md` "Adding New Components" (replace
      "Handle loading and error states" with a pointer to `Swap`/`Sk` and the rule:
      no spinners/text for region loads, footprint-matched skeletons only).

### Phase 1 — Shared chokepoints (~25 screens fixed in 3 files)

- [ ] `AdminTable`: add a `loading` prop that renders N skeleton rows mirroring the
      actual column definitions (use each column's width/alignment; badge-shaped
      blocks for badge columns, line blocks for text).
- [ ] `AdminSection`: drop the `if (isLoading) return <LoadingState/>` early return.
      Render the real header (search input + create button are static chrome — show
      them immediately) and pass `loading` through to the table skeleton. Remove the
      `loadingLabel` prop and its 17 call sites.
- [ ] `App.tsx` `PageFallback`: replace full-screen "Loading…" with an app-shell
      skeleton (page-title line + content blocks). Also covers `BootstrapGate`.
- [ ] Verify the admin pages that bypass AdminSection (`PluginsManagement`,
      `AuthProvidersManagement`, `PluginEntityManagement`, `AdminOverview`) against
      the new primitives; convert their `LoadingState` uses.

### Phase 2 — Core pages

- [ ] `ProjectsView`: skeleton table matching the projects grid/row footprint;
      remove "Loading projects..." text; keep filter chrome visible immediately.
- [ ] `ProjectDetailPage` + `ProjectDetail`: stop blocking on the project fetch —
      render header skeleton (name line, badges, score), then per-region `Swap`s
      for overview cards (score trend, breakdown, environments, links, integrations)
      so the page resolves in waves. Stagger reveals `delay={i * 50}`.
- [ ] `Dashboard` widgets: footprint pass — skeleton rows must match real row
      internals (avatar circle + two lines + badge), not single `h-16` blocks;
      sweep via new primitive; per-widget reveal (already independent queries).
- [ ] `OperationsLog`: replace `LoadingState` with feed-row skeletons (timeline dot +
      line composition matching `OperationsLogFeedItem`); drop the page-level
      `inert`/opacity overlay in favor of per-region `aria-busy`; metadata queries
      (projects/envs/users) must not gate the feed; next-page fetch shows 2–3
      skeleton rows instead of "Loading more…" text.
- [ ] `CommandBar` SearchResultsPanel: result-card skeletons instead of "Searching…".

### Phase 3 — Project detail tabs (one PR per tab is reasonable)

- [ ] `DeploymentsTab`: un-gate the three queries — env sidebar, history, and commit
      cards each get their own `Swap`; skeleton mirrors env rail + stage cards.
- [ ] `ReleasesTab`: drift card and history table reveal independently.
- [ ] `DependenciesTab`: skeleton list for dependencies; don't block on releases query.
- [ ] `ProjectDocumentsTab`: pinboard card skeletons.
- [ ] `ConfigurationTab`: per-environment column skeletons (keys list per env reveals
      as its query lands) instead of single left-panel label.
- [ ] `IncidentsTab`, `LogsTab`: row skeletons matching their tables; histogram block
      for LogsTab.
- [ ] `ProjectPullRequestsTab`: upgrade generic rows to footprint (icon, title line,
      state badge, avatar, diff bar, timestamp blocks).
- [ ] `ProjectRelationshipsTab`: graph-area block + sidebar line skeletons; guard the
      `length === 0` sub-sections with loading state.
- [ ] `ScoreHistoryTab`: chart-area block + event-row skeletons; **fix the empty-state
      flash** — "No score data / no change events" must only render when the query
      has settled.
- [ ] `ProjectDoctorTab`, `ProjectActivityLog`: replace spinner/text with row skeletons.
- [ ] `IntegrationsCard`, `ProjectPluginsSection`: small row skeletons; fix silent/blank
      loading.
- [ ] `DeployTab` + `deploy/lists.tsx`: upgrade existing skeletons to sweep + multi-column
      footprint (sha block + message line + author + badge); keep their `aria-busy`
      (now via `Swap`). `PromoteTab`: replace "Loading commits…" with commit-row skeletons.
- [ ] `EnvironmentNav` (deployments): replace the size-13 Loader2 with rail skeleton.

### Phase 4 — Remaining surfaces

- [ ] Admin detail views (`RoleDetail`, `UserDetail`, `TeamDetail`, `OrganizationDetail`,
      `EnvironmentDetail`, `WebhookDetail`, `ThirdPartyServiceDetail`, `BlueprintDetail`,
      `PluginPackageDetail`): header + field-grid skeletons; RoleDetail's 5 queries
      reveal per-section.
- [ ] `AnchorEdgesCard`: skeleton lines; fix "Not mapped to any…" flash.
- [ ] `ServiceAccountForm` edit-mode: field skeletons while the deep fetch runs.
- [ ] `SettingsConnections` (un-gate plugins vs identities), `SettingsApiKeys`,
      `SettingsNotifications`/`SettingsSecurity` (audit during implementation).
- [ ] Reports: `TeamKPIReport` (un-gate rollup vs teams), `OpenPullRequestsReport`,
      `ScoreHistoryReport`, `MonthlyImprovementReport`, `ProjectsGraphReport`.
- [ ] `UserProfilePage`: per-card reveals (header, heatmap, stats, activity) instead of
      gating on 4 queries; `ContributionHeatmap` grid skeleton.
- [ ] `RecentActivity` (+ widget): row skeletons; next-page skeleton rows instead of
      "Loading more..." button text.
- [ ] Dialogs (`NewProjectDialog`, `NewOpsLogDialog`, `EditRelationshipsDialog`):
      field/list skeletons inside the open dialog while `enabled: isOpen` queries run.
- [ ] Lazy Suspense fallbacks: `LazyProjectsGraphCanvas`/`ProjectGraphView` (canvas-area
      block, no spinner), `graph-query/ResultCard`, `LazyRichComposer` (composer-shaped
      block, no text).

### Phase 5 — AI (Imbot) amber treatment

- [ ] `CommandBar` assistant: amber `SkText` + thinking header ("Imbot is …") while the
      model works, before first token; keep streaming + caret; tool-result cards get a
      brief amber skeleton instead of popping in. Input already disabled while
      streaming — keep.
- [ ] `PendingPromoteCard` / `ReleaseReadyCard` release-notes drafting: amber skeleton +
      thinking header in the notes region; "Promote"/"Cut release" buttons stay
      disabled until generation is `done` (verify current gating).
- [ ] Confirm no plain-data fetch anywhere uses the amber variant (review pass).

### Phase 6 — Cleanup, accessibility, and guardrails

- [ ] Delete `ui/loading-state.tsx` once `grep -r "LoadingState" src` is clean —
      the build then enforces the pattern for the 21 former consumers.
- [ ] Sweep: no region-level `animate-spin` left (button/toast spinners exempt);
      no literal "Loading" text in JSX outside aria-labels.
- [ ] `aria-busy` audit: every `Swap` region toggles it; skeletons are `aria-hidden`.
- [ ] Reduced-motion manual test (macOS "Reduce motion"): skeletons static but visible,
      reveals instant, streaming collapses to instant render.
- [ ] Empty-state flash regression check: ScoreHistoryTab, AnchorEdgesCard,
      NewOpsLogDialog, ProjectRelationshipsTab.
- [ ] Add an oxlint `no-restricted-imports`/custom rule (or a CI grep) banning
      `LoadingState` re-introduction and region-level spinners, if practical.

## Acceptance criteria (per surface)

A surface is done when:
1. While its data is in flight it shows a skeleton with the same rows/widths/radii as
   the loaded content — verified by toggling network throttling and comparing layouts.
2. No layout shift when data lands; content reveals with the fade+lift (instant under
   reduced motion).
3. Sibling regions don't wait for it (each region has its own `Swap`).
4. The region container has `aria-busy` toggling; skeleton elements are `aria-hidden`.
5. No "Loading…" text, no spinner, no empty-state message before the query settles.
6. Amber is used iff the content is Imbot-generated.

## Audit tallies

- ~70 data-loading surfaces inventoried.
- text-loading (forbidden): ~38 surfaces (20 admin via `AdminSection`, 10 project tabs,
  8 elsewhere incl. route-level `PageFallback`).
- skeleton-generic (right idea, wrong execution): ~10 (dashboard widgets, deploy lists,
  AdminOverview, OperationsLogSummary, ProjectPullRequestsTab).
- region spinners (forbidden): 6 (graph canvas ×2, ProjectActivityLog, EnvironmentNav,
  EditRelationshipsDialog, search panel).
- silent/blank loaders: ~12 (admin detail views, dialogs, IntegrationsCard,
  ProjectPluginsSection, AnchorEdgesCard).
- Empty-state flash bugs: ScoreHistoryTab (worst), AnchorEdgesCard, NewOpsLogDialog,
  ProjectRelationshipsTab sub-sections.
- Fully conforming today: 0.
