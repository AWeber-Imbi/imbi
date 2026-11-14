import {
  createContext,
  type Dispatch,
  type ReactNode,
  type RefObject,
  type SetStateAction,
  useContext,
  useEffect,
  useState,
} from 'react'

import { Search, X } from 'lucide-react'

const HIGHLIGHT = 'task-search'
const MAX_MARKS = 2000

type SearchState = [string, Dispatch<SetStateAction<string>>]

const TaskSearchContext = createContext<null | SearchState>(null)

export function matches(text: string, query: string): boolean {
  const q = query.trim().toLowerCase()
  return !q || text.toLowerCase().includes(q)
}

/** Keeps one search query for every view of a task, so it survives a tab switch. */
export function TaskSearchProvider({ children }: { children: ReactNode }) {
  const state = useState('')
  return (
    <TaskSearchContext.Provider value={state}>
      {children}
    </TaskSearchContext.Provider>
  )
}

/** The search box of a task view, styled like the header search. */
export function ToolbarSearch({
  label,
  onChange,
  value,
}: {
  label: string
  onChange: (value: string) => void
  value: string
}) {
  return (
    <label className="border-tertiary bg-primary focus-within:border-action flex h-8 w-56 min-w-0 shrink items-center gap-2 rounded-lg border pr-1 pl-2.5">
      <Search aria-hidden className="text-tertiary size-4 shrink-0" />
      <input
        aria-label={label}
        className="text-primary placeholder:text-tertiary min-w-0 flex-1 bg-transparent text-sm outline-none [&::-webkit-search-cancel-button]:appearance-none"
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') onChange('')
        }}
        placeholder="Search"
        type="search"
        value={value}
      />
      {value && (
        <button
          aria-label="Clear search"
          className="text-tertiary hover:bg-tertiary hover:text-primary flex size-6 shrink-0 items-center justify-center rounded-md"
          onClick={() => onChange('')}
          type="button"
        >
          <X aria-hidden className="size-3.5" />
        </button>
      )}
    </label>
  )
}

/** Marks every match of the query inside the element, and keeps the marks as it changes. */
export function useSearchHighlight(
  ref: RefObject<HTMLElement | null>,
  query: string,
) {
  useEffect(() => {
    const root = ref.current
    const q = query.trim().toLowerCase()
    if (typeof CSS === 'undefined' || !('highlights' in CSS) || !root) return
    if (!q) {
      CSS.highlights.delete(HIGHLIGHT)
      return
    }
    let frame = 0
    const mark = () => {
      const ranges: Range[] = []
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        const text = (n.textContent ?? '').toLowerCase()
        for (
          let i = text.indexOf(q);
          i !== -1 && ranges.length < MAX_MARKS;
          i = text.indexOf(q, i + q.length)
        ) {
          const range = new Range()
          range.setStart(n, i)
          range.setEnd(n, i + q.length)
          ranges.push(range)
        }
      }
      CSS.highlights.set(HIGHLIGHT, new Highlight(...ranges))
    }
    mark()
    const observer = new MutationObserver(() => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(mark)
    })
    observer.observe(root, {
      characterData: true,
      childList: true,
      subtree: true,
    })
    return () => {
      observer.disconnect()
      cancelAnimationFrame(frame)
      CSS.highlights.delete(HIGHLIGHT)
    }
  }, [query, ref])
}

/** The task's shared query, or a query of its own when the view stands alone. */
export function useTaskSearch(): SearchState {
  const shared = useContext(TaskSearchContext)
  const local = useState('')
  return shared ?? local
}
