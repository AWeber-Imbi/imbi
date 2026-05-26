/* eslint-disable react-refresh/only-export-components */
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from 'react'

import { ApiError } from '@/api/client'
import { executeGraphQuery } from '@/api/endpoints'
import type {
  GraphQueryCard,
  GraphQueryCardTab,
  GraphQueryError,
  GraphQueryErrorEnvelope,
  GraphQueryHistoryEntry,
  GraphQueryResult,
} from '@/types'

const HISTORY_STORAGE_KEY = 'imbi-cypher-history'
export const HISTORY_LIMIT = 100

type CardsAction =
  | { card: GraphQueryCard; type: 'add' }
  | { id: string; tab: GraphQueryCardTab; type: 'setTab' }
  | { id: string; type: 'dismiss' }
  | { id: string; type: 'toggleCollapsed' }

interface GraphQueryContextValue {
  addCard: (card: GraphQueryCard) => void
  addToHistory: (query: string) => void
  cards: GraphQueryCard[]
  clearHistory: () => void
  dismissCard: (id: string) => void
  editorValue: string
  history: GraphQueryHistoryEntry[]
  isRunning: boolean
  runQuery: (query: string) => Promise<void>
  setCardTab: (id: string, tab: GraphQueryCardTab) => void
  setEditorValue: (value: string) => void
  toggleCardCollapsed: (id: string) => void
}

type HistoryAction =
  | { entries: GraphQueryHistoryEntry[]; type: 'init' }
  | { entry: GraphQueryHistoryEntry; type: 'add' }
  | { type: 'clear' }

export function cardsReducer(
  state: GraphQueryCard[],
  action: CardsAction,
): GraphQueryCard[] {
  switch (action.type) {
    case 'add':
      return [action.card, ...state]
    case 'dismiss':
      return state.filter((c) => c.id !== action.id)
    case 'setTab':
      return state.map((c) =>
        c.id === action.id ? { ...c, tab: action.tab } : c,
      )
    case 'toggleCollapsed':
      return state.map((c) =>
        c.id === action.id ? { ...c, collapsed: !c.collapsed } : c,
      )
  }
}

export function historyReducer(
  state: GraphQueryHistoryEntry[],
  action: HistoryAction,
): GraphQueryHistoryEntry[] {
  switch (action.type) {
    case 'add': {
      const trimmed = action.entry.query.trim()
      if (!trimmed) return state
      // Dedupe consecutive duplicates (compare against the newest entry).
      if (state[0] && state[0].query.trim() === trimmed) {
        return state
      }
      const next = [
        { executedAt: action.entry.executedAt, query: action.entry.query },
        ...state,
      ]
      return next.slice(0, HISTORY_LIMIT)
    }
    case 'clear':
      return []
    case 'init':
      return action.entries.slice(0, HISTORY_LIMIT)
  }
}

const GraphQueryContext = createContext<GraphQueryContextValue | null>(null)

export function GraphQueryProvider({ children }: { children: ReactNode }) {
  const [editorValue, setEditorValue] = useState('')
  const [cards, dispatchCards] = useReducer(cardsReducer, [])
  const [history, dispatchHistory] = useReducer(historyReducer, [])
  const [isRunning, setIsRunning] = useState(false)
  const hydratedRef = useRef(false)

  // Hydrate history from localStorage once on mount.
  useEffect(() => {
    dispatchHistory({ entries: readStoredHistory(), type: 'init' })
    hydratedRef.current = true
  }, [])

  // Persist history changes after hydration.
  useEffect(() => {
    if (!hydratedRef.current) return
    if (typeof window === 'undefined') return
    try {
      window.localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(history))
    } catch {
      // Ignore quota errors.
    }
  }, [history])

  const addCard = useCallback((card: GraphQueryCard) => {
    dispatchCards({ card, type: 'add' })
  }, [])

  const dismissCard = useCallback((id: string) => {
    dispatchCards({ id, type: 'dismiss' })
  }, [])

  const toggleCardCollapsed = useCallback((id: string) => {
    dispatchCards({ id, type: 'toggleCollapsed' })
  }, [])

  const setCardTab = useCallback((id: string, tab: GraphQueryCardTab) => {
    dispatchCards({ id, tab, type: 'setTab' })
  }, [])

  const addToHistory = useCallback((query: string) => {
    dispatchHistory({
      entry: { executedAt: Date.now(), query },
      type: 'add',
    })
  }, [])

  const clearHistory = useCallback(() => {
    dispatchHistory({ type: 'clear' })
  }, [])

  const runQuery = useCallback(async (query: string) => {
    const trimmed = query.trim()
    if (!trimmed) return

    setIsRunning(true)
    const startedAt = Date.now()
    const cardId = generateCardId()

    try {
      const result: GraphQueryResult = await executeGraphQuery({
        query: trimmed,
      })
      dispatchCards({
        card: {
          collapsed: false,
          elapsedMs: result.elapsed_ms,
          id: cardId,
          query: trimmed,
          result,
          startedAt,
          status: 'success',
          tab: 'table',
        },
        type: 'add',
      })
    } catch (err) {
      dispatchCards({
        card: {
          collapsed: false,
          elapsedMs: Date.now() - startedAt,
          error: extractErrorFromApi(err),
          id: cardId,
          query: trimmed,
          startedAt,
          status: 'error',
          tab: 'raw',
        },
        type: 'add',
      })
    } finally {
      dispatchHistory({
        entry: { executedAt: startedAt, query: trimmed },
        type: 'add',
      })
      setIsRunning(false)
    }
  }, [])

  const value = useMemo<GraphQueryContextValue>(
    () => ({
      addCard,
      addToHistory,
      cards,
      clearHistory,
      dismissCard,
      editorValue,
      history,
      isRunning,
      runQuery,
      setCardTab,
      setEditorValue,
      toggleCardCollapsed,
    }),
    [
      addCard,
      addToHistory,
      cards,
      clearHistory,
      dismissCard,
      editorValue,
      history,
      isRunning,
      runQuery,
      setCardTab,
      toggleCardCollapsed,
    ],
  )

  return (
    <GraphQueryContext.Provider value={value}>
      {children}
    </GraphQueryContext.Provider>
  )
}

export function useGraphQuery() {
  const ctx = useContext(GraphQueryContext)
  if (!ctx) {
    throw new Error('useGraphQuery must be used within a GraphQueryProvider')
  }
  return ctx
}

function extractErrorFromApi(err: unknown): GraphQueryError {
  if (err instanceof ApiError) {
    const data = err.data as GraphQueryErrorEnvelope | undefined
    if (data && typeof data === 'object' && 'error' in data && data.error) {
      return data.error
    }
    return { message: err.message || `HTTP ${err.status}` }
  }
  if (err instanceof Error) {
    return { message: err.message }
  }
  return { message: 'Unknown error' }
}

function generateCardId(): string {
  if (
    typeof globalThis.crypto !== 'undefined' &&
    typeof globalThis.crypto.randomUUID === 'function'
  ) {
    return globalThis.crypto.randomUUID()
  }
  return `card-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
}

function readStoredHistory(): GraphQueryHistoryEntry[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(HISTORY_STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as unknown
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter(
        (e): e is GraphQueryHistoryEntry =>
          typeof e === 'object' &&
          e !== null &&
          typeof (e as GraphQueryHistoryEntry).query === 'string' &&
          typeof (e as GraphQueryHistoryEntry).executedAt === 'number',
      )
      .slice(0, HISTORY_LIMIT)
  } catch {
    return []
  }
}
