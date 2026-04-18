# Inline Project Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Settings-tab forms with click-to-edit-in-place controls on the Overview tab, each committing a single RFC 6902 JSON Patch request.

**Architecture:** A shared `useInlineEdit` hook encapsulates enter/escape/blur-on-change state. Small typed wrappers (`InlineText`, `InlineTextarea`, `InlineSelect`, `InlineMultiSelect`, `InlineSwitch`, `InlineNumber`, `InlineDate`) render display↔edit modes. A `useProjectPatch` hook converts `(path, value)` into a 1-op JSON Patch mutation with optimistic cache update, rollback on error, and toast on failure.

**Tech Stack:** React 19, TypeScript, React Query v5, shadcn/ui (Radix), Tailwind, Vitest, Testing Library, sonner (toasts, already in deps).

**Spec:** `docs/superpowers/specs/2026-04-17-inline-project-editing-design.md`

---

## File Structure

**New files:**

- `src/lib/json-patch.ts` — applier for `replace`/`remove` top-level ops (optimistic update) + `PatchOperation` type
- `src/hooks/useInlineEdit.ts` — shared state machine hook
- `src/hooks/useProjectPatch.ts` — React Query mutation wrapper
- `src/components/ui/inline-edit/InlineDisplay.tsx` — shared hover+pencil row with "Add…" placeholder
- `src/components/ui/inline-edit/InlineText.tsx`
- `src/components/ui/inline-edit/InlineTextarea.tsx`
- `src/components/ui/inline-edit/InlineSelect.tsx`
- `src/components/ui/inline-edit/InlineMultiSelect.tsx`
- `src/components/ui/inline-edit/InlineSwitch.tsx`
- `src/components/ui/inline-edit/InlineNumber.tsx`
- `src/components/ui/inline-edit/InlineDate.tsx`
- `src/components/ui/inline-edit/field-policy.ts` — `isFieldEditable`, `pickInlineComponent`
- Paired `*.test.ts[x]` files for each of the above.

**Modified files:**

- `src/api/endpoints.ts` — add `patchProject` + export `PatchOperation`
- `src/App.tsx` — mount sonner `<Toaster />`
- `src/components/ProjectDetail.tsx` — replace header h1/description `<p>` and project-details rows with inline components; remove `<EditProjectForm>` from `SettingsTab`

**Deleted files:**

- `src/components/EditProjectForm.tsx` (last use removed in Task 17)

---

## Task 1: Add `patchProject` endpoint + `PatchOperation` type

**Files:**

- Modify: `src/api/endpoints.ts` (around line 172, right after `updateProject`)
- Test: no dedicated test (thin wrapper over `apiClient.patch`; covered through `useProjectPatch` tests).

- [ ] **Step 1: Add the type and endpoint**

Edit `src/api/endpoints.ts`. Immediately after the `updateProject` export, add:

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

- [ ] **Step 2: Verify build**

Run: `npm run build`
Expected: PASS (no type errors).

- [ ] **Step 3: Commit**

```bash
git add src/api/endpoints.ts
git commit -m "Add patchProject API helper and PatchOperation type"
```

---

## Task 2: Minimal JSON Patch applier

Used by `useProjectPatch`'s optimistic update. Only handles `replace` and `remove` on top-level paths — the two ops the hook ever emits.

**Files:**

- Create: `src/lib/json-patch.ts`
- Test: `src/lib/__tests__/json-patch.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `src/lib/__tests__/json-patch.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { applyJsonPatch } from '../json-patch'

describe('applyJsonPatch', () => {
  it('replaces a top-level key', () => {
    const out = applyJsonPatch(
      { name: 'old', description: 'keep' },
      [{ op: 'replace', path: '/name', value: 'new' }],
    )
    expect(out).toEqual({ name: 'new', description: 'keep' })
  })

  it('removes a top-level key', () => {
    const out = applyJsonPatch(
      { name: 'n', description: 'gone' },
      [{ op: 'remove', path: '/description' }],
    )
    expect(out).toEqual({ name: 'n' })
  })

  it('returns a new object (does not mutate input)', () => {
    const input = { name: 'a' }
    const out = applyJsonPatch(input, [{ op: 'replace', path: '/name', value: 'b' }])
    expect(input).toEqual({ name: 'a' })
    expect(out).not.toBe(input)
  })

  it('throws on unsupported op', () => {
    expect(() =>
      applyJsonPatch({}, [{ op: 'move', path: '/a', from: '/b' }]),
    ).toThrow(/unsupported/i)
  })

  it('throws on non-top-level path', () => {
    expect(() =>
      applyJsonPatch({}, [{ op: 'replace', path: '/a/b', value: 1 }]),
    ).toThrow(/top-level/i)
  })
})
```

- [ ] **Step 2: Run tests — expect failure**

Run: `npx vitest run src/lib/__tests__/json-patch.test.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

Create `src/lib/json-patch.ts`:

```ts
import type { PatchOperation } from '@/api/endpoints'

export type { PatchOperation }

/**
 * Apply JSON Patch operations to a top-level object.
 * Supports only `replace` and `remove` on top-level paths (`/<key>`).
 * Returns a new object; input is not mutated.
 */
export function applyJsonPatch<T extends Record<string, unknown>>(
  doc: T,
  ops: PatchOperation[],
): T {
  let out: Record<string, unknown> = { ...doc }
  for (const op of ops) {
    if (op.op !== 'replace' && op.op !== 'remove') {
      throw new Error(`unsupported op: ${op.op}`)
    }
    const parts = op.path.split('/')
    if (parts.length !== 2 || parts[0] !== '') {
      throw new Error(`only top-level paths supported, got: ${op.path}`)
    }
    const key = decodePointerSegment(parts[1])
    if (op.op === 'replace') {
      out = { ...out, [key]: op.value }
    } else {
      const { [key]: _removed, ...rest } = out
      out = rest
    }
  }
  return out as T
}

function decodePointerSegment(seg: string): string {
  return seg.replace(/~1/g, '/').replace(/~0/g, '~')
}
```

- [ ] **Step 4: Run tests — expect pass**

Run: `npx vitest run src/lib/__tests__/json-patch.test.ts`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/lib/json-patch.ts src/lib/__tests__/json-patch.test.ts
git commit -m "Add minimal JSON Patch applier for optimistic updates"
```

---

## Task 3: `useInlineEdit` hook

Shared state machine for every inline control.

**Files:**

- Create: `src/hooks/useInlineEdit.ts`
- Test: `src/hooks/__tests__/useInlineEdit.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `src/hooks/__tests__/useInlineEdit.test.ts`:

```ts
import { describe, it, expect, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useInlineEdit } from '../useInlineEdit'

describe('useInlineEdit', () => {
  it('starts in display mode', () => {
    const { result } = renderHook(() =>
      useInlineEdit({ initial: 'a', onCommit: vi.fn() }),
    )
    expect(result.current.isEditing).toBe(false)
    expect(result.current.draft).toBe('a')
  })

  it('enter() puts it in edit mode with draft=initial', () => {
    const { result } = renderHook(() =>
      useInlineEdit({ initial: 'a', onCommit: vi.fn() }),
    )
    act(() => result.current.enter())
    expect(result.current.isEditing).toBe(true)
    expect(result.current.draft).toBe('a')
  })

  it('cancel() restores and exits', () => {
    const { result } = renderHook(() =>
      useInlineEdit({ initial: 'a', onCommit: vi.fn() }),
    )
    act(() => result.current.enter())
    act(() => result.current.setDraft('b'))
    act(() => result.current.cancel())
    expect(result.current.isEditing).toBe(false)
    expect(result.current.draft).toBe('a')
  })

  it('commit() calls onCommit and exits on success', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    const { result } = renderHook(() =>
      useInlineEdit({ initial: 'a', onCommit }),
    )
    act(() => result.current.enter())
    act(() => result.current.setDraft('b'))
    await act(async () => {
      await result.current.commit()
    })
    expect(onCommit).toHaveBeenCalledWith('b')
    expect(result.current.isEditing).toBe(false)
    expect(result.current.error).toBeNull()
  })

  it('commit() is a no-op when draft === initial', async () => {
    const onCommit = vi.fn()
    const { result } = renderHook(() =>
      useInlineEdit({ initial: 'a', onCommit }),
    )
    act(() => result.current.enter())
    await act(async () => {
      await result.current.commit()
    })
    expect(onCommit).not.toHaveBeenCalled()
    expect(result.current.isEditing).toBe(false)
  })

  it('commit() keeps edit mode and sets error on rejection', async () => {
    const onCommit = vi.fn().mockRejectedValue(new Error('boom'))
    const { result } = renderHook(() =>
      useInlineEdit({ initial: 'a', onCommit }),
    )
    act(() => result.current.enter())
    act(() => result.current.setDraft('b'))
    await act(async () => {
      await result.current.commit()
    })
    expect(result.current.isEditing).toBe(true)
    expect(result.current.draft).toBe('b')
    expect(result.current.error).toBe('boom')
  })

  it('handleKeyDown Enter commits', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    const { result } = renderHook(() =>
      useInlineEdit({ initial: 'a', onCommit }),
    )
    act(() => result.current.enter())
    act(() => result.current.setDraft('b'))
    await act(async () => {
      await result.current.handleKeyDown({
        key: 'Enter',
        preventDefault: vi.fn(),
      } as unknown as React.KeyboardEvent)
    })
    expect(onCommit).toHaveBeenCalledWith('b')
  })

  it('handleKeyDown Escape cancels', () => {
    const { result } = renderHook(() =>
      useInlineEdit({ initial: 'a', onCommit: vi.fn() }),
    )
    act(() => result.current.enter())
    act(() => result.current.setDraft('b'))
    act(() => {
      result.current.handleKeyDown({
        key: 'Escape',
        preventDefault: vi.fn(),
      } as unknown as React.KeyboardEvent)
    })
    expect(result.current.isEditing).toBe(false)
    expect(result.current.draft).toBe('a')
  })

  it('handleBlur commits only when changed', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    const { result } = renderHook(() =>
      useInlineEdit({ initial: 'a', onCommit }),
    )
    act(() => result.current.enter())
    // unchanged blur
    await act(async () => {
      await result.current.handleBlur({} as React.FocusEvent)
    })
    expect(onCommit).not.toHaveBeenCalled()
    expect(result.current.isEditing).toBe(false)

    // changed blur
    act(() => result.current.enter())
    act(() => result.current.setDraft('b'))
    await act(async () => {
      await result.current.handleBlur({} as React.FocusEvent)
    })
    expect(onCommit).toHaveBeenCalledWith('b')
  })
})
```

- [ ] **Step 2: Run tests — expect failure**

Run: `npx vitest run src/hooks/__tests__/useInlineEdit.test.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement the hook**

Create `src/hooks/useInlineEdit.ts`:

```ts
import { useCallback, useEffect, useState } from 'react'

export interface UseInlineEditOptions<T> {
  initial: T
  onCommit: (value: T) => Promise<void> | void
  /** Compare draft and initial. Defaults to `Object.is`. */
  equals?: (a: T, b: T) => boolean
}

export interface UseInlineEditResult<T> {
  isEditing: boolean
  enter: () => void
  cancel: () => void
  commit: () => Promise<void>
  draft: T
  setDraft: (v: T) => void
  handleKeyDown: (e: React.KeyboardEvent) => void | Promise<void>
  handleBlur: (e: React.FocusEvent) => void | Promise<void>
  error: string | null
  setError: (s: string | null) => void
}

export function useInlineEdit<T>(
  opts: UseInlineEditOptions<T>,
): UseInlineEditResult<T> {
  const equals = opts.equals ?? Object.is
  const [isEditing, setEditing] = useState(false)
  const [draft, setDraft] = useState<T>(opts.initial)
  const [error, setError] = useState<string | null>(null)

  // Keep draft in sync with external value when not editing.
  useEffect(() => {
    if (!isEditing) setDraft(opts.initial)
  }, [opts.initial, isEditing])

  const enter = useCallback(() => {
    setDraft(opts.initial)
    setError(null)
    setEditing(true)
  }, [opts.initial])

  const cancel = useCallback(() => {
    setDraft(opts.initial)
    setError(null)
    setEditing(false)
  }, [opts.initial])

  const commit = useCallback(async () => {
    if (equals(draft, opts.initial)) {
      setEditing(false)
      return
    }
    try {
      await opts.onCommit(draft)
      setError(null)
      setEditing(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [draft, opts, equals])

  const handleKeyDown = useCallback(
    async (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        await commit()
      } else if (e.key === 'Escape') {
        e.preventDefault()
        cancel()
      }
    },
    [commit, cancel],
  )

  const handleBlur = useCallback(async () => {
    if (equals(draft, opts.initial)) {
      setEditing(false)
      return
    }
    await commit()
  }, [draft, opts.initial, equals, commit])

  return {
    isEditing,
    enter,
    cancel,
    commit,
    draft,
    setDraft,
    handleKeyDown,
    handleBlur,
    error,
    setError,
  }
}
```

- [ ] **Step 4: Run tests — expect pass**

Run: `npx vitest run src/hooks/__tests__/useInlineEdit.test.ts`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add src/hooks/useInlineEdit.ts src/hooks/__tests__/useInlineEdit.test.ts
git commit -m "Add useInlineEdit shared hook for inline controls"
```

---

## Task 4: `useProjectPatch` hook

Wraps the mutation, applies optimistic update + rollback, toasts on error.

**Files:**

- Create: `src/hooks/useProjectPatch.ts`
- Test: `src/hooks/__tests__/useProjectPatch.test.tsx`
- Modify: `src/App.tsx` — mount `<Toaster />` from sonner

- [ ] **Step 1: Mount Toaster in App.tsx**

Edit `src/App.tsx`. Add import at top of the file:

```tsx
import { Toaster } from 'sonner'
```

Inside the top-level JSX returned by the `App` component, add `<Toaster richColors position="top-right" />` next to the existing providers (adjacent to `<ThemeProvider>` / `<OrganizationProvider>` so it renders for every authenticated route).

- [ ] **Step 2: Write the failing tests**

Create `src/hooks/__tests__/useProjectPatch.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useProjectPatch } from '../useProjectPatch'
import * as endpoints from '@/api/endpoints'
import { toast } from 'sonner'

vi.mock('sonner', () => ({ toast: { error: vi.fn() } }))

function wrapper(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
}

const baseProject = {
  id: 'p1',
  name: 'Alpha',
  slug: 'alpha',
  description: 'desc',
  team: { slug: 't', name: 'T', organization: { slug: 'o' } },
} as unknown as import('@/types').Project

describe('useProjectPatch', () => {
  let qc: QueryClient

  beforeEach(() => {
    qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    qc.setQueryData(['project', 'o', 'p1'], baseProject)
    vi.clearAllMocks()
  })

  it('applies optimistic update and sets returned project on success', async () => {
    const updated = { ...baseProject, name: 'Beta' }
    vi.spyOn(endpoints, 'patchProject').mockResolvedValue(updated as never)

    const { result } = renderHook(() => useProjectPatch('o', 'p1'), {
      wrapper: wrapper(qc),
    })

    await act(async () => {
      await result.current.patch('/name', 'Beta')
    })

    expect(endpoints.patchProject).toHaveBeenCalledWith('o', 'p1', [
      { op: 'replace', path: '/name', value: 'Beta' },
    ])
    expect(qc.getQueryData(['project', 'o', 'p1'])).toEqual(updated)
  })

  it('rolls back on error and toasts', async () => {
    vi.spyOn(endpoints, 'patchProject').mockRejectedValue(
      Object.assign(new Error('nope'), {
        response: { data: { detail: 'nope' } },
      }),
    )

    const { result } = renderHook(() => useProjectPatch('o', 'p1'), {
      wrapper: wrapper(qc),
    })

    await expect(
      act(async () => {
        await result.current.patch('/name', 'Beta')
      }),
    ).rejects.toThrow()

    expect(qc.getQueryData(['project', 'o', 'p1'])).toEqual(baseProject)
    expect(toast.error).toHaveBeenCalled()
  })

  it('emits remove op when value is null', async () => {
    const updated = { ...baseProject }
    vi.spyOn(endpoints, 'patchProject').mockResolvedValue(updated as never)

    const { result } = renderHook(() => useProjectPatch('o', 'p1'), {
      wrapper: wrapper(qc),
    })

    await act(async () => {
      await result.current.patch('/description', null)
    })

    expect(endpoints.patchProject).toHaveBeenCalledWith('o', 'p1', [
      { op: 'remove', path: '/description' },
    ])
  })

  it('tracks pendingPath during the mutation', async () => {
    let resolveIt!: (v: unknown) => void
    vi.spyOn(endpoints, 'patchProject').mockImplementation(
      () => new Promise((r) => { resolveIt = r }),
    )

    const { result } = renderHook(() => useProjectPatch('o', 'p1'), {
      wrapper: wrapper(qc),
    })

    act(() => {
      result.current.patch('/name', 'Beta')
    })
    await waitFor(() => expect(result.current.pendingPath).toBe('/name'))

    act(() => resolveIt({ ...baseProject, name: 'Beta' }))
    await waitFor(() => expect(result.current.pendingPath).toBeNull())
  })
})
```

- [ ] **Step 3: Run tests — expect failure**

Run: `npx vitest run src/hooks/__tests__/useProjectPatch.test.tsx`
Expected: FAIL (module not found).

- [ ] **Step 4: Implement the hook**

Create `src/hooks/useProjectPatch.ts`:

```ts
import { useCallback, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { patchProject, type PatchOperation } from '@/api/endpoints'
import { applyJsonPatch } from '@/lib/json-patch'
import { ApiError } from '@/api/client'
import type { Project } from '@/types'

export interface UseProjectPatchResult {
  patch: (path: string, value: unknown) => Promise<void>
  pendingPath: string | null
}

/**
 * Build a single-op JSON Patch from (path, value). Null/undefined/''
 * become a `remove` operation; everything else becomes `replace`.
 */
function buildOp(path: string, value: unknown): PatchOperation {
  if (value === null || value === undefined || value === '') {
    return { op: 'remove', path }
  }
  return { op: 'replace', path, value }
}

export function useProjectPatch(
  orgSlug: string,
  projectId: string,
): UseProjectPatchResult {
  const qc = useQueryClient()
  const key = ['project', orgSlug, projectId] as const
  const [pendingPath, setPendingPath] = useState<string | null>(null)

  const mutation = useMutation<
    Project,
    unknown,
    PatchOperation,
    { snapshot: Project | undefined }
  >({
    mutationFn: (op) => patchProject(orgSlug, projectId, [op]),
    onMutate: async (op) => {
      setPendingPath(op.path)
      await qc.cancelQueries({ queryKey: key })
      const snapshot = qc.getQueryData<Project>(key)
      if (snapshot) {
        qc.setQueryData<Project>(
          key,
          applyJsonPatch(snapshot as unknown as Record<string, unknown>, [op]) as unknown as Project,
        )
      }
      return { snapshot }
    },
    onError: (error, _op, ctx) => {
      if (ctx?.snapshot !== undefined) {
        qc.setQueryData(key, ctx.snapshot)
      }
      const detail =
        error instanceof ApiError
          ? (error.response as { data?: { detail?: string } } | undefined)?.data?.detail ||
            error.message
          : error instanceof Error
            ? error.message
            : 'Failed to save'
      toast.error(`Save failed: ${detail}`)
    },
    onSuccess: (data) => {
      qc.setQueryData(key, data)
    },
    onSettled: () => {
      setPendingPath(null)
    },
  })

  const patch = useCallback(
    async (path: string, value: unknown) => {
      await mutation.mutateAsync(buildOp(path, value))
    },
    [mutation],
  )

  return { patch, pendingPath }
}
```

- [ ] **Step 5: Run tests — expect pass**

Run: `npx vitest run src/hooks/__tests__/useProjectPatch.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add src/hooks/useProjectPatch.ts src/hooks/__tests__/useProjectPatch.test.tsx src/App.tsx
git commit -m "Add useProjectPatch hook with optimistic update + toast"
```

---

## Task 5: Shared `InlineDisplay` component

Renders the non-edit state: value text, muted "Add…" placeholder when empty, hover-revealed pencil icon. All inline wrappers compose this for consistent affordance.

**Files:**

- Create: `src/components/ui/inline-edit/InlineDisplay.tsx`
- Test: `src/components/ui/inline-edit/__tests__/InlineDisplay.test.tsx`

- [ ] **Step 1: Write the failing tests**

Create `src/components/ui/inline-edit/__tests__/InlineDisplay.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@/test/utils'
import userEvent from '@testing-library/user-event'
import { InlineDisplay } from '../InlineDisplay'

describe('InlineDisplay', () => {
  it('renders children when value is non-empty', () => {
    render(
      <InlineDisplay hasValue onClick={vi.fn()}>
        Alpha
      </InlineDisplay>,
    )
    expect(screen.getByText('Alpha')).toBeInTheDocument()
  })

  it('renders "Add…" placeholder when hasValue is false', () => {
    render(<InlineDisplay hasValue={false} onClick={vi.fn()} />)
    expect(screen.getByText(/add/i)).toBeInTheDocument()
  })

  it('fires onClick when the row is clicked', async () => {
    const onClick = vi.fn()
    render(
      <InlineDisplay hasValue onClick={onClick}>
        Alpha
      </InlineDisplay>,
    )
    await userEvent.click(screen.getByText('Alpha'))
    expect(onClick).toHaveBeenCalled()
  })

  it('does not fire onClick when readOnly', async () => {
    const onClick = vi.fn()
    render(
      <InlineDisplay hasValue readOnly onClick={onClick}>
        Alpha
      </InlineDisplay>,
    )
    await userEvent.click(screen.getByText('Alpha'))
    expect(onClick).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run tests — expect failure**

Run: `npx vitest run src/components/ui/inline-edit/__tests__/InlineDisplay.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `src/components/ui/inline-edit/InlineDisplay.tsx`:

```tsx
import { Pencil, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface InlineDisplayProps {
  hasValue: boolean
  readOnly?: boolean
  pending?: boolean
  onClick: () => void
  className?: string
  placeholder?: string
  children?: React.ReactNode
}

export function InlineDisplay({
  hasValue,
  readOnly = false,
  pending = false,
  onClick,
  className,
  placeholder = 'Add…',
  children,
}: InlineDisplayProps) {
  const interactive = !readOnly && !pending

  return (
    <span
      role={interactive ? 'button' : undefined}
      tabIndex={interactive ? 0 : -1}
      onClick={interactive ? onClick : undefined}
      onKeyDown={
        interactive
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                onClick()
              }
            }
          : undefined
      }
      className={cn(
        'group inline-flex items-center gap-1.5',
        interactive &&
          'cursor-pointer rounded-sm hover:bg-secondary/40 focus:outline-none focus-visible:ring-1 focus-visible:ring-ring',
        className,
      )}
    >
      {hasValue ? (
        children
      ) : (
        <span className="italic text-tertiary">{placeholder}</span>
      )}
      {pending ? (
        <Loader2 className="h-3 w-3 animate-spin text-tertiary" />
      ) : interactive ? (
        <Pencil className="h-3 w-3 text-tertiary opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" />
      ) : null}
    </span>
  )
}
```

- [ ] **Step 4: Run tests — expect pass**

Run: `npx vitest run src/components/ui/inline-edit/__tests__/InlineDisplay.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/components/ui/inline-edit/InlineDisplay.tsx src/components/ui/inline-edit/__tests__/InlineDisplay.test.tsx
git commit -m "Add InlineDisplay shared row for inline controls"
```

---

## Task 6: `InlineText`

Single-line text input. Canonical implementation — subsequent wrappers mirror this shape.

**Files:**

- Create: `src/components/ui/inline-edit/InlineText.tsx`
- Test: `src/components/ui/inline-edit/__tests__/InlineText.test.tsx`

- [ ] **Step 1: Write the failing tests**

Create `src/components/ui/inline-edit/__tests__/InlineText.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@/test/utils'
import userEvent from '@testing-library/user-event'
import { InlineText } from '../InlineText'

describe('InlineText', () => {
  it('renders value in display mode', () => {
    render(<InlineText value="Alpha" onCommit={vi.fn()} />)
    expect(screen.getByText('Alpha')).toBeInTheDocument()
  })

  it('enters edit mode on click and autofocuses', async () => {
    render(<InlineText value="Alpha" onCommit={vi.fn()} />)
    await userEvent.click(screen.getByText('Alpha'))
    const input = screen.getByRole('textbox')
    expect(input).toHaveFocus()
    expect(input).toHaveValue('Alpha')
  })

  it('commits on Enter with the edited value', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    render(<InlineText value="Alpha" onCommit={onCommit} />)
    await userEvent.click(screen.getByText('Alpha'))
    const input = screen.getByRole('textbox')
    await userEvent.clear(input)
    await userEvent.type(input, 'Beta{Enter}')
    await waitFor(() => expect(onCommit).toHaveBeenCalledWith('Beta'))
  })

  it('cancels on Escape and does not commit', async () => {
    const onCommit = vi.fn()
    render(<InlineText value="Alpha" onCommit={onCommit} />)
    await userEvent.click(screen.getByText('Alpha'))
    await userEvent.keyboard('{Escape}')
    expect(onCommit).not.toHaveBeenCalled()
    expect(screen.getByText('Alpha')).toBeInTheDocument()
  })

  it('renders "Add…" when value is null and is editable', async () => {
    render(<InlineText value={null} onCommit={vi.fn()} />)
    expect(screen.getByText(/add/i)).toBeInTheDocument()
  })

  it('is not interactive when readOnly', async () => {
    render(<InlineText value="Alpha" onCommit={vi.fn()} readOnly />)
    await userEvent.click(screen.getByText('Alpha'))
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run tests — expect failure**

Run: `npx vitest run src/components/ui/inline-edit/__tests__/InlineText.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `src/components/ui/inline-edit/InlineText.tsx`:

```tsx
import { useEffect, useRef } from 'react'
import { Input } from '@/components/ui/input'
import { useInlineEdit } from '@/hooks/useInlineEdit'
import { InlineDisplay } from './InlineDisplay'
import { cn } from '@/lib/utils'

export interface InlineTextProps {
  value: string | null
  onCommit: (next: string | null) => Promise<void> | void
  readOnly?: boolean
  pending?: boolean
  placeholder?: string
  className?: string
  inputClassName?: string
  /** Render value in a custom display element; default is a plain span. */
  renderValue?: (value: string) => React.ReactNode
}

export function InlineText({
  value,
  onCommit,
  readOnly = false,
  pending = false,
  placeholder,
  className,
  inputClassName,
  renderValue,
}: InlineTextProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const edit = useInlineEdit<string>({
    initial: value ?? '',
    onCommit: async (next) => {
      await onCommit(next === '' ? null : next)
    },
  })

  useEffect(() => {
    if (edit.isEditing) inputRef.current?.focus()
  }, [edit.isEditing])

  if (!edit.isEditing) {
    const hasValue = !!value
    return (
      <span className={className}>
        <InlineDisplay
          hasValue={hasValue}
          readOnly={readOnly}
          pending={pending}
          onClick={edit.enter}
          placeholder={placeholder}
        >
          {hasValue && (renderValue ? renderValue(value!) : value)}
        </InlineDisplay>
      </span>
    )
  }

  return (
    <span className={className}>
      <Input
        ref={inputRef}
        value={edit.draft}
        onChange={(e) => edit.setDraft(e.target.value)}
        onKeyDown={edit.handleKeyDown}
        onBlur={edit.handleBlur}
        className={cn('h-7 py-1', inputClassName)}
      />
      {edit.error && (
        <span className="mt-1 block text-xs text-red-600">{edit.error}</span>
      )}
    </span>
  )
}
```

- [ ] **Step 4: Run tests — expect pass**

Run: `npx vitest run src/components/ui/inline-edit/__tests__/InlineText.test.tsx`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/components/ui/inline-edit/InlineText.tsx src/components/ui/inline-edit/__tests__/InlineText.test.tsx
git commit -m "Add InlineText component"
```

---

## Task 7: `InlineTextarea`

Multi-line. Enter inserts newline; Cmd/Ctrl+Enter commits; blur-on-change commits.

**Files:**

- Create: `src/components/ui/inline-edit/InlineTextarea.tsx`
- Test: `src/components/ui/inline-edit/__tests__/InlineTextarea.test.tsx`

- [ ] **Step 1: Write the failing tests**

Create `src/components/ui/inline-edit/__tests__/InlineTextarea.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@/test/utils'
import userEvent from '@testing-library/user-event'
import { InlineTextarea } from '../InlineTextarea'

describe('InlineTextarea', () => {
  it('commits on Cmd+Enter (or Ctrl+Enter)', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    render(<InlineTextarea value="hi" onCommit={onCommit} />)
    await userEvent.click(screen.getByText('hi'))
    const ta = screen.getByRole('textbox') as HTMLTextAreaElement
    await userEvent.clear(ta)
    await userEvent.type(ta, 'there')
    await userEvent.keyboard('{Control>}{Enter}{/Control}')
    await waitFor(() => expect(onCommit).toHaveBeenCalledWith('there'))
  })

  it('plain Enter inserts a newline and does not commit', async () => {
    const onCommit = vi.fn()
    render(<InlineTextarea value="hi" onCommit={onCommit} />)
    await userEvent.click(screen.getByText('hi'))
    const ta = screen.getByRole('textbox') as HTMLTextAreaElement
    await userEvent.type(ta, '{Enter}x')
    expect(ta.value).toContain('\n')
    expect(onCommit).not.toHaveBeenCalled()
  })

  it('Escape cancels', async () => {
    const onCommit = vi.fn()
    render(<InlineTextarea value="hi" onCommit={onCommit} />)
    await userEvent.click(screen.getByText('hi'))
    await userEvent.type(screen.getByRole('textbox'), ' edits')
    await userEvent.keyboard('{Escape}')
    expect(onCommit).not.toHaveBeenCalled()
    expect(screen.getByText('hi')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run tests — expect failure**

Run: `npx vitest run src/components/ui/inline-edit/__tests__/InlineTextarea.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `src/components/ui/inline-edit/InlineTextarea.tsx`:

```tsx
import { useEffect, useRef } from 'react'
import { Textarea } from '@/components/ui/textarea'
import { useInlineEdit } from '@/hooks/useInlineEdit'
import { InlineDisplay } from './InlineDisplay'
import { cn } from '@/lib/utils'

export interface InlineTextareaProps {
  value: string | null
  onCommit: (next: string | null) => Promise<void> | void
  readOnly?: boolean
  pending?: boolean
  placeholder?: string
  className?: string
  rows?: number
}

export function InlineTextarea({
  value,
  onCommit,
  readOnly = false,
  pending = false,
  placeholder,
  className,
  rows = 3,
}: InlineTextareaProps) {
  const ref = useRef<HTMLTextAreaElement>(null)
  const edit = useInlineEdit<string>({
    initial: value ?? '',
    onCommit: async (next) => {
      await onCommit(next === '' ? null : next)
    },
  })

  useEffect(() => {
    if (edit.isEditing) ref.current?.focus()
  }, [edit.isEditing])

  if (!edit.isEditing) {
    const hasValue = !!value
    return (
      <span className={className}>
        <InlineDisplay
          hasValue={hasValue}
          readOnly={readOnly}
          pending={pending}
          onClick={edit.enter}
          placeholder={placeholder}
        >
          {hasValue && value}
        </InlineDisplay>
      </span>
    )
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      void edit.commit()
      return
    }
    if (e.key === 'Escape') {
      e.preventDefault()
      edit.cancel()
    }
    // plain Enter: allow default newline insertion
  }

  return (
    <span className={cn('block', className)}>
      <Textarea
        ref={ref}
        rows={rows}
        value={edit.draft}
        onChange={(e) => edit.setDraft(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={edit.handleBlur}
      />
      {edit.error && (
        <span className="mt-1 block text-xs text-red-600">{edit.error}</span>
      )}
    </span>
  )
}
```

- [ ] **Step 4: Run tests — expect pass**

Run: `npx vitest run src/components/ui/inline-edit/__tests__/InlineTextarea.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/components/ui/inline-edit/InlineTextarea.tsx src/components/ui/inline-edit/__tests__/InlineTextarea.test.tsx
git commit -m "Add InlineTextarea component"
```

---

## Task 8: `InlineSelect`

Single-choice dropdown. Commits immediately on change.

**Files:**

- Create: `src/components/ui/inline-edit/InlineSelect.tsx`
- Test: `src/components/ui/inline-edit/__tests__/InlineSelect.test.tsx`

- [ ] **Step 1: Write the failing tests**

Create `src/components/ui/inline-edit/__tests__/InlineSelect.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@/test/utils'
import userEvent from '@testing-library/user-event'
import { InlineSelect } from '../InlineSelect'

const options = [
  { value: 'a', label: 'Alpha' },
  { value: 'b', label: 'Beta' },
]

describe('InlineSelect', () => {
  it('renders label for current value', () => {
    render(<InlineSelect value="a" options={options} onCommit={vi.fn()} />)
    expect(screen.getByText('Alpha')).toBeInTheDocument()
  })

  it('commits when a different option is chosen', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    render(<InlineSelect value="a" options={options} onCommit={onCommit} />)
    await userEvent.click(screen.getByText('Alpha'))
    await userEvent.click(await screen.findByRole('option', { name: 'Beta' }))
    await waitFor(() => expect(onCommit).toHaveBeenCalledWith('b'))
  })
})
```

- [ ] **Step 2: Run tests — expect failure**

Run: `npx vitest run src/components/ui/inline-edit/__tests__/InlineSelect.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `src/components/ui/inline-edit/InlineSelect.tsx`:

```tsx
import { useState } from 'react'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { InlineDisplay } from './InlineDisplay'
import { toast } from 'sonner'

export interface InlineSelectOption {
  value: string
  label: string
}

export interface InlineSelectProps {
  value: string | null
  options: InlineSelectOption[]
  onCommit: (next: string) => Promise<void> | void
  readOnly?: boolean
  pending?: boolean
  placeholder?: string
}

export function InlineSelect({
  value,
  options,
  onCommit,
  readOnly = false,
  pending = false,
  placeholder = 'Select…',
}: InlineSelectProps) {
  const [editing, setEditing] = useState(false)
  const current = options.find((o) => o.value === value)

  if (!editing) {
    return (
      <InlineDisplay
        hasValue={!!current}
        readOnly={readOnly}
        pending={pending}
        onClick={() => setEditing(true)}
        placeholder={placeholder}
      >
        {current?.label}
      </InlineDisplay>
    )
  }

  return (
    <Select
      defaultOpen
      value={value ?? undefined}
      onValueChange={async (next) => {
        setEditing(false)
        if (next === value) return
        try {
          await onCommit(next)
        } catch (e) {
          toast.error(e instanceof Error ? e.message : 'Save failed')
        }
      }}
      onOpenChange={(open) => {
        if (!open) setEditing(false)
      }}
    >
      <SelectTrigger className="h-7 py-1">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
```

- [ ] **Step 4: Run tests — expect pass**

Run: `npx vitest run src/components/ui/inline-edit/__tests__/InlineSelect.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/components/ui/inline-edit/InlineSelect.tsx src/components/ui/inline-edit/__tests__/InlineSelect.test.tsx
git commit -m "Add InlineSelect component"
```

---

## Task 9: `InlineMultiSelect`

Multi-chip picker backed by `cmdk` (already a project dep). Commits the full next list on Enter or popover close when changed.

**Files:**

- Create: `src/components/ui/inline-edit/InlineMultiSelect.tsx`
- Test: `src/components/ui/inline-edit/__tests__/InlineMultiSelect.test.tsx`

- [ ] **Step 1: Write the failing tests**

Create `src/components/ui/inline-edit/__tests__/InlineMultiSelect.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@/test/utils'
import userEvent from '@testing-library/user-event'
import { InlineMultiSelect } from '../InlineMultiSelect'

const options = [
  { value: 'a', label: 'Alpha' },
  { value: 'b', label: 'Beta' },
  { value: 'c', label: 'Charlie' },
]

describe('InlineMultiSelect', () => {
  it('renders current labels', () => {
    render(
      <InlineMultiSelect values={['a', 'b']} options={options} onCommit={vi.fn()} />,
    )
    expect(screen.getByText('Alpha, Beta')).toBeInTheDocument()
  })

  it('commits the new list when the popover closes with changes', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    render(
      <InlineMultiSelect values={['a']} options={options} onCommit={onCommit} />,
    )
    await userEvent.click(screen.getByText('Alpha'))
    await userEvent.click(await screen.findByRole('option', { name: 'Beta' }))
    await userEvent.keyboard('{Escape}')
    await waitFor(() =>
      expect(onCommit).toHaveBeenCalledWith(expect.arrayContaining(['a', 'b'])),
    )
  })
})
```

- [ ] **Step 2: Run tests — expect failure**

Run: `npx vitest run src/components/ui/inline-edit/__tests__/InlineMultiSelect.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `src/components/ui/inline-edit/InlineMultiSelect.tsx`:

```tsx
import { useState } from 'react'
import { Check } from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Command, CommandGroup, CommandInput, CommandItem } from 'cmdk'
import { InlineDisplay } from './InlineDisplay'
import { toast } from 'sonner'

export interface InlineMultiSelectOption {
  value: string
  label: string
}

export interface InlineMultiSelectProps {
  values: string[]
  options: InlineMultiSelectOption[]
  onCommit: (next: string[]) => Promise<void> | void
  readOnly?: boolean
  pending?: boolean
  placeholder?: string
}

export function InlineMultiSelect({
  values,
  options,
  onCommit,
  readOnly = false,
  pending = false,
  placeholder = 'Select…',
}: InlineMultiSelectProps) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<string[]>(values)

  const toggle = (v: string) => {
    setDraft((cur) =>
      cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v],
    )
  }

  const sameSet = (a: string[], b: string[]) =>
    a.length === b.length && a.every((x) => b.includes(x))

  const close = async () => {
    setOpen(false)
    if (sameSet(draft, values)) return
    try {
      await onCommit(draft)
    } catch (e) {
      setDraft(values)
      toast.error(e instanceof Error ? e.message : 'Save failed')
    }
  }

  const currentLabels = options
    .filter((o) => values.includes(o.value))
    .map((o) => o.label)
    .join(', ')

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        if (next) {
          setDraft(values)
          setOpen(true)
        } else {
          void close()
        }
      }}
    >
      <PopoverTrigger asChild>
        <span>
          <InlineDisplay
            hasValue={values.length > 0}
            readOnly={readOnly}
            pending={pending}
            onClick={() => setOpen(true)}
            placeholder={placeholder}
          >
            {currentLabels}
          </InlineDisplay>
        </span>
      </PopoverTrigger>
      <PopoverContent className="w-64 p-0" align="start">
        <Command>
          <CommandInput placeholder="Filter…" />
          <CommandGroup>
            {options.map((o) => {
              const checked = draft.includes(o.value)
              return (
                <CommandItem
                  key={o.value}
                  role="option"
                  aria-selected={checked}
                  onSelect={() => toggle(o.value)}
                >
                  <Check
                    className={
                      'mr-2 h-4 w-4 ' + (checked ? 'opacity-100' : 'opacity-0')
                    }
                  />
                  {o.label}
                </CommandItem>
              )
            })}
          </CommandGroup>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
```

- [ ] **Step 4: Run tests — expect pass**

Run: `npx vitest run src/components/ui/inline-edit/__tests__/InlineMultiSelect.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/components/ui/inline-edit/InlineMultiSelect.tsx src/components/ui/inline-edit/__tests__/InlineMultiSelect.test.tsx
git commit -m "Add InlineMultiSelect component"
```

---

## Task 10: `InlineSwitch`

Boolean. No separate edit mode — toggles and commits immediately.

**Files:**

- Create: `src/components/ui/inline-edit/InlineSwitch.tsx`
- Test: `src/components/ui/inline-edit/__tests__/InlineSwitch.test.tsx`

- [ ] **Step 1: Write the failing tests**

Create `src/components/ui/inline-edit/__tests__/InlineSwitch.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@/test/utils'
import userEvent from '@testing-library/user-event'
import { InlineSwitch } from '../InlineSwitch'

describe('InlineSwitch', () => {
  it('commits the toggled value', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    render(<InlineSwitch value={false} onCommit={onCommit} />)
    await userEvent.click(screen.getByRole('switch'))
    await waitFor(() => expect(onCommit).toHaveBeenCalledWith(true))
  })

  it('is disabled when readOnly', () => {
    render(<InlineSwitch value readOnly onCommit={vi.fn()} />)
    expect(screen.getByRole('switch')).toBeDisabled()
  })
})
```

- [ ] **Step 2: Run tests — expect failure**

Run: `npx vitest run src/components/ui/inline-edit/__tests__/InlineSwitch.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `src/components/ui/inline-edit/InlineSwitch.tsx`:

```tsx
import { Switch } from '@/components/ui/switch'
import { toast } from 'sonner'

export interface InlineSwitchProps {
  value: boolean | null
  onCommit: (next: boolean) => Promise<void> | void
  readOnly?: boolean
  pending?: boolean
}

export function InlineSwitch({
  value,
  onCommit,
  readOnly = false,
  pending = false,
}: InlineSwitchProps) {
  return (
    <Switch
      checked={!!value}
      disabled={readOnly || pending}
      onCheckedChange={async (next) => {
        try {
          await onCommit(next)
        } catch (e) {
          toast.error(e instanceof Error ? e.message : 'Save failed')
        }
      }}
    />
  )
}
```

- [ ] **Step 4: Run tests — expect pass**

Run: `npx vitest run src/components/ui/inline-edit/__tests__/InlineSwitch.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/components/ui/inline-edit/InlineSwitch.tsx src/components/ui/inline-edit/__tests__/InlineSwitch.test.tsx
git commit -m "Add InlineSwitch component"
```

---

## Task 11: `InlineNumber`

Numeric input; enforces `min`/`max` when provided; parses to number on commit.

**Files:**

- Create: `src/components/ui/inline-edit/InlineNumber.tsx`
- Test: `src/components/ui/inline-edit/__tests__/InlineNumber.test.tsx`

- [ ] **Step 1: Write the failing tests**

Create `src/components/ui/inline-edit/__tests__/InlineNumber.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@/test/utils'
import userEvent from '@testing-library/user-event'
import { InlineNumber } from '../InlineNumber'

describe('InlineNumber', () => {
  it('commits parsed number on Enter', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    render(<InlineNumber value={10} onCommit={onCommit} />)
    await userEvent.click(screen.getByText('10'))
    const input = screen.getByRole('spinbutton')
    await userEvent.clear(input)
    await userEvent.type(input, '42{Enter}')
    await waitFor(() => expect(onCommit).toHaveBeenCalledWith(42))
  })

  it('commits null when cleared', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    render(<InlineNumber value={10} onCommit={onCommit} />)
    await userEvent.click(screen.getByText('10'))
    const input = screen.getByRole('spinbutton')
    await userEvent.clear(input)
    await userEvent.keyboard('{Enter}')
    await waitFor(() => expect(onCommit).toHaveBeenCalledWith(null))
  })
})
```

- [ ] **Step 2: Run tests — expect failure**

Run: `npx vitest run src/components/ui/inline-edit/__tests__/InlineNumber.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `src/components/ui/inline-edit/InlineNumber.tsx`:

```tsx
import { useEffect, useRef } from 'react'
import { Input } from '@/components/ui/input'
import { useInlineEdit } from '@/hooks/useInlineEdit'
import { InlineDisplay } from './InlineDisplay'

export interface InlineNumberProps {
  value: number | null
  onCommit: (next: number | null) => Promise<void> | void
  readOnly?: boolean
  pending?: boolean
  min?: number
  max?: number
  step?: number
  placeholder?: string
  integer?: boolean
}

export function InlineNumber({
  value,
  onCommit,
  readOnly = false,
  pending = false,
  min,
  max,
  step,
  placeholder,
  integer = false,
}: InlineNumberProps) {
  const ref = useRef<HTMLInputElement>(null)
  const edit = useInlineEdit<string>({
    initial: value === null || value === undefined ? '' : String(value),
    onCommit: async (next) => {
      if (next === '') {
        await onCommit(null)
        return
      }
      const parsed = integer ? parseInt(next, 10) : parseFloat(next)
      if (Number.isNaN(parsed)) throw new Error('Not a number')
      if (min !== undefined && parsed < min) throw new Error(`Min is ${min}`)
      if (max !== undefined && parsed > max) throw new Error(`Max is ${max}`)
      await onCommit(parsed)
    },
  })

  useEffect(() => {
    if (edit.isEditing) ref.current?.focus()
  }, [edit.isEditing])

  if (!edit.isEditing) {
    return (
      <InlineDisplay
        hasValue={value !== null && value !== undefined}
        readOnly={readOnly}
        pending={pending}
        onClick={edit.enter}
        placeholder={placeholder}
      >
        {value !== null && value !== undefined ? String(value) : null}
      </InlineDisplay>
    )
  }

  return (
    <span className="block">
      <Input
        ref={ref}
        type="number"
        inputMode={integer ? 'numeric' : 'decimal'}
        min={min}
        max={max}
        step={step}
        value={edit.draft}
        onChange={(e) => edit.setDraft(e.target.value)}
        onKeyDown={edit.handleKeyDown}
        onBlur={edit.handleBlur}
        className="h-7 w-32 py-1"
      />
      {edit.error && (
        <span className="mt-1 block text-xs text-red-600">{edit.error}</span>
      )}
    </span>
  )
}
```

- [ ] **Step 4: Run tests — expect pass**

Run: `npx vitest run src/components/ui/inline-edit/__tests__/InlineNumber.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/components/ui/inline-edit/InlineNumber.tsx src/components/ui/inline-edit/__tests__/InlineNumber.test.tsx
git commit -m "Add InlineNumber component"
```

---

## Task 12: `InlineDate`

Date / date-time picker using `react-day-picker` (already in deps) inside a popover.

**Files:**

- Create: `src/components/ui/inline-edit/InlineDate.tsx`
- Test: `src/components/ui/inline-edit/__tests__/InlineDate.test.tsx`

- [ ] **Step 1: Write the failing tests**

Create `src/components/ui/inline-edit/__tests__/InlineDate.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@/test/utils'
import userEvent from '@testing-library/user-event'
import { InlineDate } from '../InlineDate'

describe('InlineDate', () => {
  it('opens the calendar and commits an ISO date on day select', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    render(
      <InlineDate value="2026-04-10" onCommit={onCommit} mode="date" />,
    )
    await userEvent.click(screen.getByText(/2026/))
    // react-day-picker renders day buttons with `role=gridcell` -> button inside
    const day15 = await screen.findByRole('button', { name: /15/ })
    await userEvent.click(day15)
    await waitFor(() =>
      expect(onCommit).toHaveBeenCalledWith(expect.stringMatching(/2026-04-15/)),
    )
  })
})
```

- [ ] **Step 2: Run tests — expect failure**

Run: `npx vitest run src/components/ui/inline-edit/__tests__/InlineDate.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `src/components/ui/inline-edit/InlineDate.tsx`:

```tsx
import { useState } from 'react'
import { DayPicker } from 'react-day-picker'
import 'react-day-picker/dist/style.css'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { InlineDisplay } from './InlineDisplay'
import { toast } from 'sonner'

export interface InlineDateProps {
  value: string | null
  onCommit: (next: string | null) => Promise<void> | void
  readOnly?: boolean
  pending?: boolean
  placeholder?: string
  /** 'date' → YYYY-MM-DD, 'date-time' → ISO 8601 string */
  mode?: 'date' | 'date-time'
}

function toIso(d: Date, mode: 'date' | 'date-time'): string {
  if (mode === 'date') return d.toISOString().slice(0, 10)
  return d.toISOString()
}

export function InlineDate({
  value,
  onCommit,
  readOnly = false,
  pending = false,
  placeholder,
  mode = 'date',
}: InlineDateProps) {
  const [open, setOpen] = useState(false)
  const current = value ? new Date(value) : undefined
  const hasValid = !!current && !Number.isNaN(current.getTime())

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <span>
          <InlineDisplay
            hasValue={hasValid}
            readOnly={readOnly}
            pending={pending}
            onClick={() => setOpen(true)}
            placeholder={placeholder}
          >
            {hasValid && current!.toLocaleDateString()}
          </InlineDisplay>
        </span>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-2" align="start">
        <DayPicker
          mode="single"
          selected={hasValid ? current : undefined}
          onSelect={async (d) => {
            setOpen(false)
            if (!d) return
            try {
              await onCommit(toIso(d, mode))
            } catch (e) {
              toast.error(e instanceof Error ? e.message : 'Save failed')
            }
          }}
        />
      </PopoverContent>
    </Popover>
  )
}
```

- [ ] **Step 4: Run tests — expect pass**

Run: `npx vitest run src/components/ui/inline-edit/__tests__/InlineDate.test.tsx`
Expected: PASS (1 test).

- [ ] **Step 5: Commit**

```bash
git add src/components/ui/inline-edit/InlineDate.tsx src/components/ui/inline-edit/__tests__/InlineDate.test.tsx
git commit -m "Add InlineDate component"
```

---

## Task 13: Field policy helpers

`isFieldEditable` and `pickInlineComponent` for schema-driven rows.

**Files:**

- Create: `src/components/ui/inline-edit/field-policy.ts`
- Test: `src/components/ui/inline-edit/__tests__/field-policy.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `src/components/ui/inline-edit/__tests__/field-policy.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import {
  isFieldEditable,
  pickInlineComponent,
  READ_ONLY_KEYS,
} from '../field-policy'

describe('isFieldEditable', () => {
  it('returns false for read-only keys', () => {
    expect(isFieldEditable('id', {})).toBe(false)
    expect(isFieldEditable('created_at', {})).toBe(false)
  })

  it('respects x-ui.editable=false', () => {
    expect(isFieldEditable('foo', { 'x-ui': { editable: false } })).toBe(false)
  })

  it('defaults to editable', () => {
    expect(isFieldEditable('foo', { type: 'string' })).toBe(true)
  })
})

describe('pickInlineComponent', () => {
  it('picks select for enum', () => {
    expect(pickInlineComponent({ enum: ['a', 'b'] })).toBe('select')
  })
  it('picks switch for boolean', () => {
    expect(pickInlineComponent({ type: 'boolean' })).toBe('switch')
  })
  it('picks date for date/date-time', () => {
    expect(pickInlineComponent({ format: 'date' })).toBe('date')
    expect(pickInlineComponent({ format: 'date-time' })).toBe('date')
  })
  it('picks number for integer/number', () => {
    expect(pickInlineComponent({ type: 'integer' })).toBe('number')
    expect(pickInlineComponent({ type: 'number' })).toBe('number')
  })
  it('picks text by default', () => {
    expect(pickInlineComponent({})).toBe('text')
  })
})

describe('READ_ONLY_KEYS', () => {
  it('includes id/created_at/updated_at', () => {
    expect(READ_ONLY_KEYS.has('id')).toBe(true)
    expect(READ_ONLY_KEYS.has('created_at')).toBe(true)
    expect(READ_ONLY_KEYS.has('updated_at')).toBe(true)
  })
})
```

- [ ] **Step 2: Run tests — expect failure**

Run: `npx vitest run src/components/ui/inline-edit/__tests__/field-policy.test.ts`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `src/components/ui/inline-edit/field-policy.ts`:

```ts
import type { ProjectSchemaSectionProperty } from '@/api/endpoints'

export const READ_ONLY_KEYS: ReadonlySet<string> = new Set([
  'id',
  'created_at',
  'updated_at',
])

export type InlineKind = 'text' | 'select' | 'switch' | 'number' | 'date'

export function isFieldEditable(
  key: string,
  def: Pick<ProjectSchemaSectionProperty, 'x-ui'> | Record<string, unknown>,
): boolean {
  if (READ_ONLY_KEYS.has(key)) return false
  const xUi = (def as ProjectSchemaSectionProperty)['x-ui']
  if (xUi && xUi.editable === false) return false
  return true
}

export function pickInlineComponent(
  def: Partial<ProjectSchemaSectionProperty>,
): InlineKind {
  if (def.enum && def.enum.length > 0) return 'select'
  if (def.type === 'boolean') return 'switch'
  if (def.format === 'date' || def.format === 'date-time') return 'date'
  if (def.type === 'integer' || def.type === 'number') return 'number'
  return 'text'
}
```

- [ ] **Step 4: Run tests — expect pass**

Run: `npx vitest run src/components/ui/inline-edit/__tests__/field-policy.test.ts`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add src/components/ui/inline-edit/field-policy.ts src/components/ui/inline-edit/__tests__/field-policy.test.ts
git commit -m "Add field-policy helpers for inline editing"
```

---

## Task 14: Wire header (name + description) in ProjectDetail

**Files:**

- Modify: `src/components/ProjectDetail.tsx` (header block around lines 388-466)

- [ ] **Step 1: Add imports + patch hook near the top of `ProjectDetail`**

At the top of `src/components/ProjectDetail.tsx` add:

```tsx
import { InlineText } from '@/components/ui/inline-edit/InlineText'
import { InlineTextarea } from '@/components/ui/inline-edit/InlineTextarea'
import { useProjectPatch } from '@/hooks/useProjectPatch'
```

Inside the `ProjectDetail` component body, right after `const orgSlug = selectedOrganization?.slug || ''`, add:

```tsx
const { patch, pendingPath } = useProjectPatch(orgSlug, project.id)
```

- [ ] **Step 2: Replace the `<h1>` with `InlineText`**

Locate the header section:

```tsx
<h1 className={`text-[1.75rem] ${value}`}>{project.name}</h1>
```

Replace with:

```tsx
<InlineText
  value={project.name}
  onCommit={(v) => patch('/name', v ?? '')}
  pending={pendingPath === '/name'}
  className="text-[1.75rem]"
  renderValue={(v) => <span className={`text-[1.75rem] ${value}`}>{v}</span>}
/>
```

(Name is required — empty string round-trips; the backend rejects blank with 400, surfacing as inline error.)

- [ ] **Step 3: Replace the description `<p>`**

Locate:

```tsx
{project.description && (
  <p className={'mt-3 text-secondary'}>{project.description}</p>
)}
```

Replace with an always-rendered inline control (shows "Add a description…" when empty):

```tsx
<div className="mt-3 text-secondary">
  <InlineTextarea
    value={project.description ?? null}
    onCommit={(v) => patch('/description', v)}
    pending={pendingPath === '/description'}
    placeholder="Add a description…"
    rows={2}
  />
</div>
```

- [ ] **Step 4: Typecheck + build**

Run: `npm run build`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/components/ProjectDetail.tsx
git commit -m "Make project name and description inline-editable"
```

---

## Task 15: Wire Team, Slug, Project types rows in Project details card

**Files:**

- Modify: `src/components/ProjectDetail.tsx` (Team row ~line 499, Slug row ~line 509, add Project Types row)

- [ ] **Step 1: Add imports and data queries**

Near the existing imports add:

```tsx
import { InlineSelect } from '@/components/ui/inline-edit/InlineSelect'
import { InlineMultiSelect } from '@/components/ui/inline-edit/InlineMultiSelect'
import { listTeams, listProjectTypes } from '@/api/endpoints'
```

Inside `ProjectDetail`, after the existing `useQuery` calls for link defs and project schema, add:

```tsx
const { data: teams = [] } = useQuery({
  queryKey: ['teams', orgSlug],
  queryFn: () => listTeams(orgSlug),
  enabled: !!orgSlug,
})
const { data: projectTypes = [] } = useQuery({
  queryKey: ['projectTypes', orgSlug],
  queryFn: () => listProjectTypes(orgSlug),
  enabled: !!orgSlug,
})
```

- [ ] **Step 2: Replace the Team row**

Locate:

```tsx
<span className={`text-sm ${value}`}>
  {project.team.name}
</span>
```

Replace with:

```tsx
<InlineSelect
  value={project.team.slug}
  options={teams.map((t) => ({ value: t.slug, label: t.name }))}
  onCommit={(v) => patch('/team_slug', v)}
  pending={pendingPath === '/team_slug'}
/>
```

- [ ] **Step 3: Replace the Slug row**

Locate:

```tsx
<span className={`font-mono text-sm ${value}`}>
  {project.slug}
</span>
```

Replace with:

```tsx
<InlineText
  value={project.slug}
  onCommit={(v) => patch('/slug', v ?? '')}
  pending={pendingPath === '/slug'}
  renderValue={(v) => <span className={`font-mono text-sm ${value}`}>{v}</span>}
/>
```

- [ ] **Step 4: Remove the header `<Badge>` of project types and add a Project Types row to the details card**

In the header (around line 393-396) delete:

```tsx
<Badge variant="outline">
  {(project.project_types || []).map((pt) => pt.name).join(', ')}
</Badge>
```

In the Project details card, immediately after the Slug row's closing `</div>` and before `{project.created_at && (`, add:

```tsx
<div
  className={`flex items-center justify-between border-b py-1.5 ${divider}`}
>
  <span className={`text-sm ${label}`}>Project types</span>
  <InlineMultiSelect
    values={(project.project_types || []).map((pt) => pt.slug)}
    options={projectTypes.map((pt) => ({
      value: pt.slug,
      label: pt.name,
    }))}
    onCommit={(v) => patch('/project_type_slugs', v)}
    pending={pendingPath === '/project_type_slugs'}
  />
</div>
```

- [ ] **Step 5: Typecheck**

Run: `npm run build`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/components/ProjectDetail.tsx
git commit -m "Make team, slug, and project types inline-editable"
```

---

## Task 16: Wire dynamic attribute rows via schema mapping

**Files:**

- Modify: `src/components/ProjectDetail.tsx` (the `attributeFields.map(...)` block, ~line 541-602)

- [ ] **Step 1: Add imports**

```tsx
import {
  isFieldEditable,
  pickInlineComponent,
} from '@/components/ui/inline-edit/field-policy'
import { InlineSwitch } from '@/components/ui/inline-edit/InlineSwitch'
import { InlineNumber } from '@/components/ui/inline-edit/InlineNumber'
import { InlineDate } from '@/components/ui/inline-edit/InlineDate'
```

- [ ] **Step 2: Expand `attributeFields` to include the raw `def`**

In the `attributeFields` `useMemo` (line 321), alongside the existing fields, include the raw `def` so the renderer can pick the right component:

```tsx
fields.push({
  key,
  label: def.title || formatFieldKey(key),
  value: formatFieldValue(raw, def),
  rawValue: raw,
  title: isDate && raw != null ? new Date(String(raw)).toLocaleString() : undefined,
  uiMaps: {
    colorMap: xUi?.['color-map'] ?? undefined,
    iconMap: xUi?.['icon-map'] ?? undefined,
    colorRange: xUi?.['color-range'] ?? undefined,
    iconRange: xUi?.['icon-range'] ?? undefined,
    colorAge: xUi?.['color-age'] ?? undefined,
    iconAge: xUi?.['icon-age'] ?? undefined,
  },
  def,
})
```

Update the local array element type to include `def: ProjectSchemaSectionProperty`.

- [ ] **Step 3: Replace the attribute row render**

Inside the `attributeFields.map(...)` block, replace the existing "non-null value" branch (the `<span className="flex items-center gap-1.5">…</span>` that renders the display value) with a branch that picks the right inline component when the field is editable, and keeps the current display otherwise:

```tsx
const editable = isFieldEditable(key, def)

const rightSide = editable
  ? renderInlineForField(key, def, rawValue, (v) => patch(`/${key}`, v), pendingPath === `/${key}`)
  : /* existing display branch kept as-is */
    fieldValue !== null ? (
      <span className="flex items-center gap-1.5">
        {FieldIcon && (
          <FieldIcon className={`h-3.5 w-3.5 flex-shrink-0 ${textColorClass}`} />
        )}
        {fieldTitle ? (
          <TooltipProvider delayDuration={200}>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className={`text-sm ${textColorClass} cursor-help underline decoration-dotted`}>
                  {fieldValue}
                </span>
              </TooltipTrigger>
              <TooltipContent>
                <p>{fieldTitle}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ) : (
          <span className={`text-sm ${textColorClass}`}>{fieldValue}</span>
        )}
      </span>
    ) : (
      <span className={`text-sm italic ${muted}`}>Not set</span>
    )
```

Then render `rightSide` in place of the existing branch.

- [ ] **Step 4: Add the local `renderInlineForField` helper inside `ProjectDetail`**

Place immediately above `return (` in the component:

```tsx
function renderInlineForField(
  key: string,
  def: ProjectSchemaSectionProperty,
  raw: unknown,
  onCommit: (v: unknown) => Promise<void>,
  pending: boolean,
): React.ReactNode {
  const kind = pickInlineComponent(def)
  switch (kind) {
    case 'select':
      return (
        <InlineSelect
          value={raw == null ? null : String(raw)}
          options={(def.enum ?? []).map((v) => ({
            value: String(v),
            label: String(v),
          }))}
          onCommit={(v) => onCommit(v)}
          pending={pending}
        />
      )
    case 'switch':
      return (
        <InlineSwitch
          value={raw === true || raw === 'true'}
          onCommit={(v) => onCommit(v)}
          pending={pending}
        />
      )
    case 'number':
      return (
        <InlineNumber
          value={raw == null || raw === '' ? null : Number(raw)}
          integer={def.type === 'integer'}
          min={def.minimum ?? undefined}
          max={def.maximum ?? undefined}
          onCommit={(v) => onCommit(v)}
          pending={pending}
        />
      )
    case 'date':
      return (
        <InlineDate
          value={raw == null ? null : String(raw)}
          mode={def.format === 'date-time' ? 'date-time' : 'date'}
          onCommit={(v) => onCommit(v)}
          pending={pending}
        />
      )
    default:
      return (
        <InlineText
          value={raw == null ? null : String(raw)}
          onCommit={(v) => onCommit(v)}
          pending={pending}
        />
      )
  }
}
```

- [ ] **Step 5: Typecheck**

Run: `npm run build`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/components/ProjectDetail.tsx
git commit -m "Make blueprint-driven project attributes inline-editable"
```

---

## Task 17: Remove `EditProjectForm` and its Settings-tab slot

**Files:**

- Modify: `src/components/ProjectDetail.tsx` (SettingsTab around line 1128-1130)
- Delete: `src/components/EditProjectForm.tsx`

- [ ] **Step 1: Remove `<EditProjectForm>` usage**

In `SettingsTab`, delete this block:

```tsx
<EditProjectForm project={project} />
```

And remove the import at the top:

```tsx
import { EditProjectForm } from '@/components/EditProjectForm'
```

- [ ] **Step 2: Delete the file**

```bash
git rm src/components/EditProjectForm.tsx
```

- [ ] **Step 3: Confirm no other references**

Run: `grep -rn "EditProjectForm" src`
Expected: no matches.

- [ ] **Step 4: Typecheck + lint + tests**

Run these sequentially:

```bash
npm run build
npm run lint
npm test
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Remove EditProjectForm in favor of inline editing"
```

---

## Task 18: Manual smoke in the dev server

Not an automated task — human verification that the whole flow works end-to-end.

- [ ] **Step 1: Start the dev server**

Run: `npm run dev`

- [ ] **Step 2: Open a project detail page in the browser**

Navigate to any project. Verify:

- Hovering the project name shows a pencil; clicking enters edit mode; Enter saves; Escape discards.
- Description shows "Add a description…" when empty; typing and blurring saves.
- Team row opens a select; changing value saves via PATCH (check Network tab: `PATCH /organizations/.../projects/...` with body `[{op:"replace", path:"/team_slug", value:"..."}]`).
- Slug row edits like text.
- Project types row opens a multi-select popover.
- Blueprint attribute rows: editable ones open the appropriate control; fields marked `x-ui.editable=false` show no pencil and are not clickable.
- Induce an error (temporarily disable network, or edit to an invalid value): toast appears, field value rolls back, inline red error appears.

- [ ] **Step 3: Settings tab**

Navigate to the Settings tab. Verify only the Links, Environments, Identifiers, Archive, Delete cards remain. No "Edit project" form.

- [ ] **Step 4: No commit** (step is verification only — any fixes become their own follow-up commits).

---

## Self-Review checklist

Before execution begins, the implementer (or plan executor) should confirm:

- **Spec coverage:**
  - Name/description in header inline-editable → Tasks 6, 7, 14.
  - Team / slug / project types inline-editable → Tasks 6, 8, 9, 15.
  - Blueprint attribute rows inline-editable with `x-ui.editable=false` respected → Tasks 10, 11, 12, 13, 16.
  - Enter saves · Escape cancels · Blur saves-if-changed → Task 3 (`useInlineEdit`).
  - Optimistic update + rollback + toast on PATCH failure → Task 4 (`useProjectPatch`).
  - Settings tab cleanup → Task 17.
- **No placeholders:** every task includes complete code.
- **Type consistency:** `PatchOperation` defined in Task 1 and re-exported from `src/lib/json-patch.ts` (Task 2). `InlineText` props remain consistent across callers in Tasks 14/15/16.
- **Open item:** the spec flags that `_execute_project_update` may not persist blueprint extras. Task 18 verifies this empirically; if failures surface, open a backend issue — out of scope here.
