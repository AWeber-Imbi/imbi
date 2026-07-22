# imbi-ui Refactor Plan

**Audited:** 2026-05-21
**Scope:** `src/` (314 .ts/.tsx files)
**Method:** Three parallel audits — duplicate code & TanStack Query inefficiencies, shared-utility adoption, shadcn/ui primitive adoption.

This document is both an issue register and an execution plan. Each item links the audit finding to a proposed fix and a rough cost estimate. Treat the **Phase** ordering as the recommended path: phases unblock each other.

Confidence is annotated per item (H/M/L). Items marked **H** are directly verified against source; **M** items need a quick spot-check before the fix lands.

---

## Phase 0 — Bugs & small cleanups

> **Implementation status (2026-05-21):** PRs #305, #306, #307, #308, #309 land items 0.1, 0.2, 0.4, 0.5, 0.6 respectively. 0.3 is deferred (audit was wrong); 0.7 needs product input. While shipping these, the original audit's framing for 0.1 and 0.3 was found to overstate the bug — both have been corrected below.

Each item ships as its own scoped PR.

### 0.1 Centralize auth-provider query keys ✅ shipped in #305
- **Audit correction:** the original framing as a behavior bug ("every change requires a hard reload") was wrong. The `invalidateAll()` helper in `AuthProvidersManagement.tsx:151-154` does invalidate both keys, and every mutation calls it.
- The two endpoints (`/auth/providers` for LoginPage, `/admin/auth-providers` for admin) return different shapes for different consumers, so two cache keys is correct — not a duplication bug.
- **Real problem:** the dual-invalidate rule was tribal knowledge inside `invalidateAll()`, with literals scattered across three files.
- **Fix shipped:** `queryKeys.adminAuthProviders / publicAuthProviders / adminLocalAuth` with a comment documenting why both must be invalidated together.

### 0.2 Unify `projectTypes` / `project-types` cache keys ✅ shipped in #306
- Real bug: 7 sites used `['projectTypes', orgSlug]`; one site (`ServicePluginConfiguration.tsx:764`) used kebab-case `['project-types', orgSlug]`. `useAdminCrud` only invalidates the camelCase variant, so the service-plugin configuration page kept stale data after admin edits.
- **Fix shipped:** `queryKeys.projectTypes(orgSlug)`; all 8 sites migrated.

### 0.3 `getQueryKeysForResource()` literals — DEFERRED (audit was wrong)
- **Audit correction:** every literal in `getQueryKeysForResource` actually matches the keys consumers use. The assistant's tool enum (`imbi-assistant/client_tools.py:53-63`) is `[projects, project_types, environments, teams, organizations, blueprints, roles, users, service_accounts]` and every case maps to a key in active use (verified for each via grep).
- **Remaining low-value work:** add a regression test pinning the resource→key mapping. Deferred behind higher-impact items.

### 0.4 Stable keys on removable lists ✅ shipped in #307
- Real bugs at two sites: `LogsTab.tsx:910` (field-filter chips removable by index — strings are deduplicated on insert so the string itself is a safe key) and `RecentActivity.tsx:85` (mixed-type activity feed).
- The other ScoreHistoryTab / LogsTab call-sites in the original audit were not actually removable-list bugs and were left alone (notes in the PR body).
- **Fix shipped:** filter-string keys in LogsTab; composite `activityKey()` helper in RecentActivity (`ops-${id}` or `feed-${project_id}-${what}-${when}`).

### 0.5 Route RecentActivity through shared `formatRelativeDate` ✅ shipped in #308
- Real bugs in `RecentActivity.getRelativeTime`: stripped `console.warn`/`console.error` in prod, ugly `Invalid date: <iso>` and `unknown time` fallbacks shown to users.
- **UX trade-off accepted:** output changes from "5 minutes ago" long form to "5m ago" compact form (the format already used everywhere else).
- **Not changed:** `documents/documentsHelpers.ts` `relativeShort()` keeps a deliberate ">8w → date string" fallback (`"Jan 14"` instead of `"3mo ago"`). Left as a documents-specific variant.

### 0.6 Use shared `<Gravatar>` in RecentActivity ✅ shipped in #309
- Real bug: hand-built URLs with `d=identicon` while every other site uses `<Gravatar>` (default `d=mp`). Same user → two different avatars.
- **Fix shipped:** `<Gravatar email={...} size={40} />`; orphan `md5` / `@types/md5` deps removed.

### 0.7 Production console diagnostics dropped — OPEN QUESTION (M)
- `vite.config.ts` `esbuild.drop: ['console']` strips all `console.*` in prod.
- `src/hooks/useAuth.ts:46,68,79,89` rely on `console.error` for auth-failure telemetry.
- **Open question:** is the silent prod the intentional product policy, or should `console.error` survive for auth diagnostics? Fix options: narrow `drop` to `['console.log','console.debug']`, or route auth diagnostics through a dedicated logger.

---

## Phase 1 — Missing shadcn primitives

These primitives don't exist in `src/components/ui/`. Add them first; several Phase 2/3 sweeps depend on them.

### 1.1 `skeleton.tsx` (H)
- 15 hand-rolled `animate-pulse` divs across:
  - `src/components/Dashboard.tsx:356`
  - `src/components/ProjectDetail.tsx:714`
  - All `src/components/dashboard/widgets/*Widget.tsx`
  - `src/components/operations-log/OperationsLogSummary.tsx:25`
  - `src/components/project/ProjectPullRequestsTab.tsx:240`
  - `src/components/reports/OpenPullRequestsReport.tsx:571`
- **Fix:** add canonical shadcn `Skeleton` to `src/components/ui/skeleton.tsx`; migrate.

### 1.2 `alert.tsx` (H)
- Info/warning banners reinvented in:
  - `src/components/admin/AuthProvidersManagement.tsx:217,250`
  - `src/components/deploy/DeployTab.tsx:262,572`
  - `src/components/deploy/PromoteTab.tsx:263-269`
  - `src/components/deploy/DeploymentModal.tsx:147`
- **Fix:** add `Alert` with `variant="info" | "warning" | "danger" | "success"`; migrate.

### 1.3 `useClipboard()` hook (H)
- 13 sites reimplement `navigator.clipboard.writeText(...); setCopied(true); setTimeout(() => setCopied(false), 2000)`:
  - `src/components/admin/blueprints/BlueprintDetail.tsx:57,127-131`
  - `src/components/admin/service-accounts/RevealSecret.tsx:33,36-39`
  - `src/components/admin/third-party-services/ApplicationSecretsPanel.tsx:59,101-103`
  - `src/components/admin/ScoringPolicyManagement.tsx:62,118-126`
  - `src/components/admin/BlueprintManagement.tsx:60,166-175`
  - `src/components/settings/SettingsApiKeys.tsx:28,66-68`
- **Fix:** add `src/hooks/useClipboard.ts` returning `{ copied, copy(text) }`.

### 1.4 `<RequiredAsterisk />` primitive (H)
- 20+ inline `<span className="text-red-500">*</span>` across forms in `NewProjectDialog`, `NewOpsLogDialog`, `AuthProvidersManagement`, `OrganizationForm`, `BlueprintForm`, `PluginEntityManagement`.
- **Fix:** add a tiny primitive (or a `required` prop on `<Label>`).

---

## Phase 2 — Performance (no UI changes)

Each item here is invisible to users but eliminates re-render storms.

### 2.1 Zustand selectors (H)
- `src/hooks/useAuth.ts:23-30`, `src/contexts/OrganizationContext.tsx:34`, `src/pages/OAuthCallbackPage.tsx:13`, `src/components/CommandBar.tsx:77` destructure entire stores.
- **Effect:** every store update re-renders every consumer. `useAuth` is at the top of the tree, so any token mutation currently re-renders the whole app.
- **Fix:** `const accessToken = useAuthStore(s => s.accessToken)` per field, or `useShallow` for grouped selections.

### 2.2 `ProjectDetail.tsx` query gating (M)
- Fires 11 sequential `useQuery` calls at first paint (lines 132, 243, 249, 256, 265, 335, 341, 346, 351, 368, 400, 416, 495).
- Tab-specific ones (`scoreTrend`, `projectBreakdown`, `currentReleases`, `myIdentities`, `identityPlugins`) load regardless of active tab.
- **Fix:** push tab-scoped queries into their tab components; gate with `enabled: activeTab === '...'`. Spot-check each query for whether the parent header/sidebar consumes its result before moving it.
- **Expected:** cold-load RTTs from ~11 to ~4.

### 2.3 `select` on `projectPlugins` (H)
- `src/components/ProjectDetail.tsx:368-385` calls `.some(a => a.tab === 'X')` four times per render.
- **Fix:** use `select` on the query to compute `{ hasConfig, hasLogs, hasLifecycle, deploymentPlugin }` once.

### 2.4 Tighten `staleTime` on hot data (H)
- `src/components/Dashboard.tsx:202` (`me-identities`), `src/hooks/useGithubLogin.ts:17`, `src/components/ProjectActivityLog.tsx:68`, `src/components/project/LogsTab.tsx:416` use the default `staleTime: 0` and refetch on every focus.
- **Fix:** pick a sensible `staleTime` per resource (typically 1–10 min).

### 2.5 `OrganizationContext` re-render storm (H)
- `src/contexts/OrganizationContext.tsx:62-70` builds `value` whose `organizations` reference changes on every refetch.
- **Effect:** every `useOrganization()` consumer re-renders on each refetch.
- **Fix:** memoize `organizations` by a stable hash, or split into `orgs` + `selectedOrg` providers.

### 2.6 Shared resource hooks (M)
- `listTeams(orgSlug)` is called from 8 places; `listEnvironments` from 9; `listProjectTypes` from 7. Same key but inconsistent `staleTime` (e.g. `ProjectActivityLog.tsx:88` uses `10 * 60_000` while everywhere else uses the default).
- **Fix:** add `src/hooks/useTeams.ts`, `useEnvironments.ts`, `useProjectTypes.ts` wrapping `useQuery` with canonical key + `staleTime` + `select`. Lint to forbid inline `queryKey: [...]` in app code.

### 2.7 Extend `useAdminCrud` with optimistic updates (M)
- `src/components/admin/AuthProvidersManagement.tsx:120-147` is the only admin page with optimistic updates (`localAuth`).
- All 13 admin pages currently wait for the round-trip then refetch the whole list.
- **Fix:** add optimistic create/update/delete to `useAdminCrud`. Also fold `AuthProvidersManagement`, `PluginEntityManagement`, `PluginsManagement` back onto `useAdminCrud` (they currently bypass it).

### 2.8 Surgical cache updates for edge mutations (M)
- `src/components/admin/.../AnchorEdgesCard.tsx` and `ServicePluginEdgesCard.tsx` invalidate `queryKeys.pluginEntities(...)` after every edge edit, refetching the whole table.
- **Fix:** use `queryClient.setQueryData(...)` to surgically update.

### 2.9 Memoize row components on long lists (H)
- `src/components/ScoreHistoryTab.tsx:416-417` has `onMouseEnter`/`onMouseLeave` lambdas inside a `.map()` over 100+ rows. Combined with index keys (see 0.4), this is also why hover state bleeds across deletes.
- **Fix:** extract a memoized `<ScoreEventRow onHover={...} index={i} />` so the lambdas are stable.

---

## Phase 3 — Shared utility adoption

### 3.1 Consolidate `formatDate` (H)
- 8 files redeclare a local `formatDate` instead of importing from `@/lib/formatDate`:
  - `src/components/admin/UserManagement.tsx:117-126`
  - `src/components/admin/ServiceAccountManagement.tsx:116-126`
  - `src/components/admin/users/UserDetail.tsx:121-130`
  - `src/components/admin/users/UserForm.tsx:226-235`
  - `src/components/admin/service-accounts/ApiKeysSection.tsx:39-48`
  - `src/components/admin/service-accounts/ClientCredentialsSection.tsx:56-65`
  - `src/components/admin/roles/RoleDetail.tsx:515,622`
  - `src/components/ProjectDetail.tsx:915`
- **Fix:** add `formatDateTime` to `@/lib/formatDate` (the local variants want time as well as date), then mass-replace.

### 3.2 `<UserDisplay>` adoption (H)
- 6 inline reinventions of `<Gravatar/> + name + email + /users/:email link`:
  - `src/components/admin/UserManagement.tsx:267-279`
  - `src/components/admin/users/UserDetail.tsx:146-154`
  - `src/components/admin/teams/TeamDetail.tsx:273`
  - `src/components/admin/roles/RoleDetail.tsx:485-499`
  - `src/components/Navigation.tsx:237-251`
  - `src/pages/UserProfile/ProfileHeader.tsx:13,21-29`
- **Also:** delete `getDisplayName` in `src/components/ProjectActivityLog.tsx:300-305` — it duplicates the `displayNames?.get(email) ?? email.split('@')[0]` fallback already in `<UserDisplay>`.

### 3.3 `<LoadingState>` adoption (H)
- Inline `Loading…` divs in:
  - `src/components/RecentActivity.tsx:62`
  - `src/components/settings/SettingsApiKeys.tsx:89`
  - `src/components/ScoreHistoryTab.tsx:300,352`
  - `src/components/reports/TeamKPIReport.tsx:125,150`
  - `src/components/reports/ScoreHistoryReport.tsx:112,136`
  - `src/components/reports/MonthlyImprovementReport.tsx:182`
  - `src/components/project/LogsTab.tsx:1043`

### 3.4 `<ErrorBanner>` adoption (H)
- `src/components/auth/LocalLoginForm.tsx:72-90`
- `src/components/admin/organizations/OrganizationForm.tsx:111-115`
- `src/components/OperationsLog.tsx:609`

---

## Phase 4 — shadcn primitive sweeps

### 4.1 Native `title=` → `<Tooltip>` (H)
- 32 files. Highest user-visible win because icon-only delete buttons are unusable on touch.
- Worst offenders:
  - `src/components/admin/users/UserForm.tsx:900`
  - `src/components/admin/teams/TeamDetail.tsx:301,331`
  - `src/components/admin/roles/RoleDetail.tsx:737`
  - `src/components/admin/third-party-services/{OAuth2ApplicationList,ServicePluginList,ServiceWebhookList}.tsx`
  - `src/components/project/LogsTab.tsx:1536-1554`
  - `src/components/ProjectsGraphCanvas.tsx:266-308` (5 toolbar buttons)
  - `src/components/Admin.tsx:272`
- **Fix:** codemod `title="X"` on `<Button>`/`<button>`/`<a>` → wrap with `<Tooltip><TooltipTrigger asChild>…</TooltipTrigger><TooltipContent>X</TooltipContent></Tooltip>`.

### 4.2 Native `<select>` → `<Select>` (H)
- 22 files, almost entirely in `src/components/admin/`. Cluster fix:
  - `src/components/admin/UserManagement.tsx:231-250`
  - `src/components/admin/AuthProvidersManagement.tsx:503-512,830`
  - `src/components/admin/blueprints/BlueprintSchemaPropertyRow.tsx:115,254,313`
  - `src/components/admin/ScoringPolicyManagement.tsx:203`
  - `src/components/admin/BlueprintManagement.tsx:303`
  - `src/components/admin/environments/EnvironmentForm.tsx`
  - `src/components/admin/users/UserForm.tsx`
  - `src/components/admin/webhooks/WebhookForm.tsx`
  - `src/components/reports/MonthlyImprovementReport.tsx`

### 4.3 Raw `<button>` ghost-pill → `<Button variant="ghost">` (M)
- 54 files / 121 occurrences. Mechanical. Exact ghost-pill reinventions:
  - `src/components/ProjectDetail.tsx:991`
  - `src/components/ScoreHistoryTab.tsx:339`
  - `src/components/Settings.tsx:65`
  - `src/components/ProjectsView.tsx:917,973,1185`

### 4.4 Hex colors → CSS variables (H)
- `src/components/ProjectActivityLog.tsx:49-51` (`#3d86d1`, `#888780`, `#ef9f27`)
- `src/components/ScoreHistoryTab.tsx:48-76` (5 chart dot colors)
- `src/components/search/SearchResultsPanel.tsx:35-54` (12 entity-type color pairs)
- `src/components/ProjectsGraphCanvas.tsx:172,178` (`#f59e0b`, `#64748b`)
- **Fix:** define semantic vars (`--color-activity-info`, `--color-entity-project`, etc.) in `index.css`; reference via `bg-[var(--…)]` or extend Tailwind theme.

### 4.5 Token color classes (H)
- Inline red/green/yellow Tailwind classes that should use design tokens:
  - `src/components/settings/SettingsSecurity.tsx:46`
  - `src/components/EditRelationshipsDialog.tsx:229,235,264`
  - `src/components/admin/users/UserForm.tsx:742-746` (password strength bar)
  - `src/components/ProjectSettingsTab.tsx:283,314`

### 4.6 Card-pattern divs → `<Card>` (M)
- 41 occurrences of `border + rounded + p-*` that are content cards, not layout panels. Audit one-by-one — not all are violations.
- Clear cases:
  - `src/components/ProjectDetail.tsx:1263` (meta-info panel)
  - `src/components/settings/SettingsApiKeys.tsx:104`
  - `src/components/deploy/DeployTab.tsx:262,572` info paragraphs

---

## What's already clean

- No Framer Motion, no non-Chart.js charts.
- No `fixed inset-0` modal reinventions — `<Dialog>` is used.
- `<Badge>` is well-adopted; no `bg-X-100 text-X-800` pill anti-pattern.
- `extractApiErrorDetail`, `slugify`, `useFormScaffold` adoption is consistent.
- lucide-react and date-fns are imported by name (tree-shakable).

---

## Execution notes

- **One PR per Phase 0 bug** — they are behavior changes and want isolated revert paths.
- **Phase 1 primitives can land together** in a single "platform" PR; they're additive.
- **Phase 2 perf items** are mostly small targeted PRs (selectors, query gating). The `ProjectDetail` gating (2.2) wants a dedicated PR with manual tab-by-tab smoke test.
- **Phase 3/4 sweeps** are codemod-friendly. Land per cluster (admin, deploy, project, reports) so reviews stay scoped to a directory each.
- Add ESLint rules as the sweeps complete to prevent regression:
  - Forbid `queryKey: [...]` outside `lib/queryKeys.ts`.
  - Forbid `title=` on `<Button>` / `<button>`.
  - Forbid `text-red-500`, `text-green-600`, etc. (allowlist amber tokens).
  - Forbid `navigator.clipboard.writeText` outside `useClipboard`.
  - Forbid `new Date(...).toLocaleString` outside `lib/formatDate.ts`.

## Open questions

1. **`useAdminCrud` extensibility.** Phase 2.7 assumes `useAdminCrud` is the right place to centralize optimistic updates. Worth a quick design review before the rewrite — three pages (`AuthProvidersManagement`, `PluginEntityManagement`, `PluginsManagement`) bypass it today and we don't know why.
2. **Console drop policy.** Phase 0.7 needs product input — do we want any auth telemetry in prod, or is the Vite drop intentional?
3. **`alert.tsx` variants.** Phase 1.2 — confirm the four variants (info/warning/danger/success) match the design system tokens before implementation.
