# Inline Project Editing — Design

**Date:** 2026-04-17
**Status:** Approved, implementation pending
**Backend dependency:** `AWeber-Imbi/imbi-api` `feature/json-patch` branch — adds
`PATCH /organizations/{org_slug}/projects/{project_id}` (RFC 6902).

## Goal

Move project editing out of the Settings tab and into the Overview tab as
click-to-edit-in-place controls. Each commit is a single JSON Patch request.

## Scope

**In:**

- Project name (header `<h1>`)
- Project description (under header)
- Project details rows: Team, Slug, Project types, and all blueprint-driven
  attribute rows (`attributeFields`) whose schema does not set
  `x-ui.editable = false`.

**Out (stay in Settings tab):**

- Links (`EditLinksCard`)
- Environments (`EditEnvironmentsCard`)
- Identifiers (`EditableKeyValueCard`)
- Archive and delete actions

**Cleanup:** `EditProjectForm` and the "Project Details" portion of the
Settings tab are removed; the tab keeps links/environments/identifiers plus
archive/delete.

## UX contract

**Edit affordance**

- Display mode renders the value as it does today.
- Empty/nullable values render a muted "Add…" affordance in place of "Not set".
- On row hover, a pencil icon appears next to the value. Clicking the value
  OR the pencil enters edit mode.
- Fields marked read-only (see below) show no hover pencil, no "Add…"
  affordance, and are not clickable.

**Read-only rules**

- Computed or system fields: `id`, `created_at`, `updated_at`, relationship
  counts.
- Blueprint-driven attributes where `def['x-ui']?.editable === false`.

**Keyboard / commit semantics** (identical for every inline control)

- **Enter** → commit.
- **Escape** → cancel (discard draft, exit edit mode).
- **Blur** → commit **only if draft !== current value**; otherwise just exit
  edit mode (no network call).
- Commit is suppressed when `draft === current` even under Enter.
- For `InlineTextarea`: Enter inserts a newline; **Cmd/Ctrl+Enter** commits.

**Error feedback**

- On a failed PATCH, revert the optimistic value, stay in edit mode with
  the draft preserved, render a red message below the input (server detail
  if available), and surface a toast.
- On success, exit edit mode and absorb the server response into the React
  Query cache.

**Concurrency**

- At most one in-flight edit per path at a time. The hook tracks
  `pendingPath`; a row whose path is pending renders a small spinner and
  ignores new Enter presses until the mutation resolves.

## Architecture

```
ProjectDetail.tsx
  ├── <InlineText      value=name        path=/name              />
  ├── <InlineTextarea  value=description path=/description       />
  └── Project details card rows:
        ├── <InlineSelect     options=teams        path=/team_slug          />
        ├── <InlineText       value=slug            path=/slug              />
        ├── <InlineMultiSelect options=projectTypes path=/project_type_slugs />
        └── schema-driven rows (see "Schema → component mapping")

Every onCommit(v) → useProjectPatch().patch(path, v)
                    → PATCH /organizations/{org}/projects/{project_id}
                      Content-Type: application/json
                      Body: PatchOperation[]
```

## Components

### `useInlineEdit<T>` hook (shared state machine)

```ts
function useInlineEdit<T>(opts: {
  initial: T
  onCommit: (value: T) => Promise<void> | void
  parse?: (rawInput: string) => T
}): {
  isEditing: boolean
  enter: () => void
  cancel: () => void
  commit: () => Promise<void>
  draft: T
  setDraft: (v: T) => void
  handleKeyDown: (e: KeyboardEvent) => void  // Enter / Escape
  handleBlur: (e: FocusEvent) => void        // commits only if changed
  error: string | null
  setError: (s: string | null) => void
}
```

Rules:

- `commit` invokes `onCommit` only when `draft !== initial` (deep-equal for
  arrays/objects); otherwise just exits edit mode silently.
- If `onCommit` rejects, the hook stays in edit mode, keeps `draft`, and
  sets `error`.
- On successful commit, exits edit mode and clears draft (the canonical
  next value comes from the caller's updated `initial` prop after React
  Query cache refresh).

### Typed inline wrappers

Each is a thin component (~40–60 lines) that renders a display fragment
and an edit fragment, wired through `useInlineEdit`. All render the hover
pencil and the "Add…" placeholder the same way via a shared
`<InlineDisplay>` helper.

- `InlineText` — single-line `<Input>`.
- `InlineTextarea` — `<Textarea>`; newline on Enter, commit on
  Cmd/Ctrl+Enter.
- `InlineSelect` — shadcn `<Select>`. Commits on value change.
- `InlineMultiSelect` — chip picker backed by a combobox/popover. Commits
  the entire next list when the user presses Enter or closes the popover
  with changes.
- `InlineSwitch` — toggles and commits immediately on change.
- `InlineNumber` — numeric `<Input>`; `min`/`max` from schema when present.
- `InlineDate` — shadcn calendar in a popover; commits on day-click.

### `useProjectPatch(orgSlug, projectId)` hook

```ts
function useProjectPatch(orgSlug, projectId): {
  patch: (path: string, value: unknown) => Promise<void>
  pendingPath: string | null
}
```

Behavior:

- Wraps a React Query `useMutation` around a new
  `patchProject(orgSlug, id, ops)` endpoint (see below).
- `patch(path, value)`:
  - If `value === null` or `''` for a nullable field → emit
    `{ op: 'remove', path }`.
  - Else → emit `{ op: 'replace', path, value }`.
- `onMutate`: snapshot the `['project', orgSlug, projectId]` cache, then
  apply the optimistic update with a local helper that handles the two
  ops we emit (`replace` and `remove`) on top-level project paths. No
  extra dependency — `fast-json-patch` is not currently in the project.
- `onError`: restore snapshot, show toast, rethrow so
  `useInlineEdit.onCommit` receives the rejection.
- `onSuccess`: write the returned `ProjectResponse` into the cache as the
  authoritative state.
- `pendingPath` tracks the path currently in flight, or `null`.

### Schema → component mapping

Applied only to blueprint-driven attribute rows; core rows map directly to
a specific wrapper.

```ts
function pickInlineComponent(def: ProjectSchemaProperty):
  - def.enum?.length          → InlineSelect
  - def.type === 'boolean'    → InlineSwitch
  - def.format === 'date' ||
    def.format === 'date-time'→ InlineDate
  - def.type === 'integer' ||
    def.type === 'number'     → InlineNumber
  - otherwise                 → InlineText
```

`isFieldEditable(key, def)` returns `false` when the key is in the
read-only set or `def['x-ui']?.editable === false`.

## Data flow

1. User clicks value / pencil → `useInlineEdit.enter()`.
2. User edits draft.
3. User presses Enter, or blurs with changes → `useInlineEdit.commit()`.
4. `commit` calls the caller's `onCommit`, which is
   `useProjectPatch().patch(path, value)`.
5. `patch` dispatches a mutation with a 1-op JSON Patch body. Optimistic
   update flips the value in the cache immediately.
6. Server responds:
   - **200** → cache replaced with authoritative `ProjectResponse`; hook
     exits edit mode.
   - **400 / 409 / 422 / 5xx** → cache rolled back; hook re-enters error
     state in edit mode; toast shown.

## API additions (UI side)

`src/api/endpoints.ts`:

```ts
export type PatchOperation = {
  op: 'add' | 'remove' | 'replace' | 'move' | 'copy' | 'test'
  path: string
  value?: unknown
  from?: string
}

export const patchProject = (
  orgSlug: string,
  projectId: string,
  operations: PatchOperation[],
) =>
  apiClient.patch<Project>(
    `/organizations/${encodeURIComponent(orgSlug)}/projects/${encodeURIComponent(projectId)}`,
    operations,
  )
```

`updateProject` (PUT) is kept — still used by Settings tab cards.

## Option sources

- Teams list for `InlineSelect` on `/team_slug`: `listTeams(orgSlug)` via
  React Query, keyed `['teams', orgSlug]`.
- Project types for `InlineMultiSelect` on `/project_type_slugs`:
  `listProjectTypes(orgSlug)` via React Query, keyed
  `['projectTypes', orgSlug]`.
- Enum options for blueprint select rows: from the schema `enum` array;
  display labels use existing icon/color maps from `x-ui` the same way the
  current display row does.

## Testing

- **Unit — `useInlineEdit`:** enter/commit/cancel/blur-without-change paths;
  error state retention; Cmd/Ctrl+Enter in textarea mode.
- **Unit — `useProjectPatch`:** optimistic update + rollback using MSW
  handlers for 200 / 400 / 409 / network error; `pendingPath` gating.
- **Component — `ProjectDetail` overview:**
  - Editing `name` fires `PATCH` with
    `[{ op: 'replace', path: '/name', value: '…' }]`.
  - Clearing a nullable blueprint field fires `remove`.
  - Rows with `x-ui.editable=false` are not clickable and show no pencil.
  - Error path shows inline red + preserves draft.
- **Regression:** existing Settings tab tests for links / environments /
  identifiers continue to pass.

## Migration / cleanup

- Delete `src/components/EditProjectForm.tsx`.
- Remove `<EditProjectForm>` usage from the `SettingsTab` in
  `ProjectDetail.tsx`.
- Keep `EditLinksCard`, `EditEnvironmentsCard`, `EditableKeyValueCard` in
  Settings unchanged.

## Out of scope

- Inline icon picker on the project header.
- Inline editing of links, environments, identifiers.
- Bulk "Save all" — every commit is atomic by design.
- Auto-save debouncing — commits are explicit (Enter or blur-on-change).

## Open items / flags

- **Backend — blueprint extras round-trip through PATCH:** `ProjectUpdate`
  is declared with `extra='allow'`, but the PATCH handler's `patchable`
  dict only includes named fields. Must verify end-to-end that
  blueprint-extended fields written via PATCH are persisted back to the
  Project node. If not, a small backend follow-up is required before
  blueprint attribute rows can be edited inline. Core-field editing works
  regardless.
