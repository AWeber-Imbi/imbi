import { useEffect, useMemo, useRef } from 'react'

import {
  defaultKeymap,
  history,
  historyKeymap,
  indentWithTab,
} from '@codemirror/commands'
import { Compartment, EditorState } from '@codemirror/state'
import {
  EditorView,
  keymap,
  placeholder as placeholderExt,
} from '@codemirror/view'

import { useTheme } from '@/contexts/ThemeContext'

interface PromptBodyEditorProps {
  ariaLabel: string
  maxHeight?: string
  minHeight?: string
  onChange: (value: string) => void
  placeholder?: string
  readOnly?: boolean
  value: string
}

const MONO = 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Monaco, monospace'

/**
 * Plain-text CodeMirror 6 editor for prompt templates. Built on the
 * same pattern as the graph-query `CypherEditor`, without a language
 * mode: Jinja templates read best as plain monospace text.
 */
export function PromptBodyEditor({
  ariaLabel,
  maxHeight = '420px',
  minHeight = '240px',
  onChange,
  placeholder = 'System prompt. Use {{ variable }} for template values.',
  readOnly = false,
  value,
}: PromptBodyEditorProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const viewRef = useRef<EditorView | null>(null)
  const onChangeRef = useRef(onChange)
  const themeCompartmentRef = useRef(new Compartment())
  const readOnlyCompartmentRef = useRef(new Compartment())
  const { isDarkMode } = useTheme()

  useEffect(() => {
    onChangeRef.current = onChange
  }, [onChange])

  const baseTheme = useMemo(
    () =>
      EditorView.theme(
        {
          '&': {
            backgroundColor: 'transparent',
            color: 'var(--ds-text-primary)',
            fontFamily: MONO,
            fontSize: '12px',
          },
          '&.cm-focused': { outline: 'none' },
          '&.cm-focused .cm-selectionBackground, ::selection': {
            backgroundColor: 'var(--background-color-amber-bg)',
          },
          '.cm-content': {
            caretColor: 'var(--ds-text-primary)',
            lineHeight: '1.7',
            minHeight,
            padding: '12px 0',
          },
          '.cm-cursor': { borderLeftColor: 'var(--ds-text-primary)' },
          '.cm-line': { padding: '0 14px' },
          '.cm-placeholder': {
            color: 'var(--ds-text-tertiary)',
            fontStyle: 'normal',
          },
          '.cm-scroller': { fontFamily: MONO, maxHeight, overflow: 'auto' },
        },
        { dark: isDarkMode },
      ),
    [isDarkMode, minHeight, maxHeight],
  )

  useEffect(() => {
    if (!containerRef.current || viewRef.current) return
    const state = EditorState.create({
      doc: value,
      extensions: [
        keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
        history(),
        EditorView.lineWrapping,
        placeholderExt(placeholder),
        EditorView.contentAttributes.of({ 'aria-label': ariaLabel }),
        themeCompartmentRef.current.of(baseTheme),
        readOnlyCompartmentRef.current.of(EditorState.readOnly.of(readOnly)),
        EditorView.updateListener.of((vu) => {
          if (vu.docChanged) onChangeRef.current(vu.state.doc.toString())
        }),
      ],
    })
    viewRef.current = new EditorView({ parent: containerRef.current, state })
    return () => {
      viewRef.current?.destroy()
      viewRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    viewRef.current?.dispatch({
      effects: themeCompartmentRef.current.reconfigure(baseTheme),
    })
  }, [baseTheme])

  useEffect(() => {
    viewRef.current?.dispatch({
      effects: readOnlyCompartmentRef.current.reconfigure(
        EditorState.readOnly.of(readOnly),
      ),
    })
  }, [readOnly])

  useEffect(() => {
    const view = viewRef.current
    if (!view) return
    const current = view.state.doc.toString()
    if (current === value) return
    view.dispatch({ changes: { from: 0, insert: value, to: current.length } })
  }, [value])

  return <div ref={containerRef} />
}
