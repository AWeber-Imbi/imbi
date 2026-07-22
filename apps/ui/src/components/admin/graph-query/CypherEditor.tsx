import { useEffect, useMemo, useRef } from 'react'

import {
  defaultKeymap,
  history,
  historyKeymap,
  indentWithTab,
} from '@codemirror/commands'
import { StreamLanguage } from '@codemirror/language'
import { cypher } from '@codemirror/legacy-modes/mode/cypher'
import { Compartment, EditorState, Prec } from '@codemirror/state'
import {
  EditorView,
  keymap,
  placeholder as placeholderExt,
} from '@codemirror/view'

import { useTheme } from '@/contexts/ThemeContext'

interface CypherEditorProps {
  autoFocus?: boolean
  maxHeight?: string
  minHeight?: string
  onChange: (value: string) => void
  onSubmit: () => void
  placeholder?: string
  value: string
}

/**
 * Minimal CodeMirror 6 editor that:
 *  - highlights Cypher via the legacy stream parser
 *  - runs onSubmit on Cmd/Ctrl+Enter
 *  - allows Shift+Enter for newlines (Enter alone also inserts a newline,
 *    matching standard editor behaviour while keeping ⌘⏎ as run)
 *  - respects the app theme via CSS variables
 */
export function CypherEditor({
  autoFocus = false,
  maxHeight = '200px',
  minHeight = '40px',
  onChange,
  onSubmit,
  placeholder = 'Enter a Cypher query and press ⌘⏎ to run',
  value,
}: CypherEditorProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const viewRef = useRef<EditorView | null>(null)
  const onChangeRef = useRef(onChange)
  const onSubmitRef = useRef(onSubmit)
  const themeCompartmentRef = useRef(new Compartment())
  const { isDarkMode } = useTheme()

  // Keep latest callbacks accessible without remounting the editor.
  useEffect(() => {
    onChangeRef.current = onChange
  }, [onChange])

  useEffect(() => {
    onSubmitRef.current = onSubmit
  }, [onSubmit])

  const baseTheme = useMemo(
    () =>
      EditorView.theme(
        {
          '&': {
            backgroundColor: 'transparent',
            color: 'var(--ds-text-primary)',
            fontFamily:
              'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Monaco, monospace',
            fontSize: '13px',
          },
          '&.cm-focused': {
            outline: 'none',
          },
          '&.cm-focused .cm-selectionBackground, ::selection': {
            backgroundColor: 'var(--background-color-amber-bg)',
          },
          '.cm-content': {
            caretColor: 'var(--ds-text-primary)',
            minHeight,
            padding: '8px 0',
          },
          '.cm-cursor': {
            borderLeftColor: 'var(--ds-text-primary)',
          },
          '.cm-line': {
            padding: '0 8px',
          },
          '.cm-placeholder': {
            color: 'var(--ds-text-tertiary)',
            fontStyle: 'normal',
          },
          '.cm-scroller': {
            fontFamily:
              'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Monaco, monospace',
            maxHeight,
            overflow: 'auto',
          },
          '.tok-comment': {
            color: 'var(--ds-text-tertiary)',
            fontStyle: 'italic',
          },
          '.tok-keyword': {
            color: 'var(--text-color-amber-text-mid)',
            fontWeight: '500',
          },
          '.tok-number': {
            color: 'var(--ds-text-primary)',
          },
          '.tok-operator': {
            color: 'var(--ds-text-secondary)',
          },
          '.tok-string': {
            color: 'var(--ds-text-primary)',
          },
          '.tok-variableName': {
            color: 'var(--ds-text-primary)',
          },
        },
        { dark: isDarkMode },
      ),
    [isDarkMode, minHeight, maxHeight],
  )

  // Build the editor once.
  useEffect(() => {
    if (!containerRef.current) return
    if (viewRef.current) return

    const runKeymap = Prec.highest(
      keymap.of([
        {
          key: 'Mod-Enter',
          run: () => {
            onSubmitRef.current()
            return true
          },
        },
      ]),
    )

    const updateListener = EditorView.updateListener.of((vu) => {
      if (vu.docChanged) {
        onChangeRef.current(vu.state.doc.toString())
      }
    })

    const state = EditorState.create({
      doc: value,
      extensions: [
        runKeymap,
        keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
        history(),
        StreamLanguage.define(cypher),
        EditorView.lineWrapping,
        placeholderExt(placeholder),
        themeCompartmentRef.current.of(baseTheme),
        updateListener,
      ],
    })

    const view = new EditorView({
      parent: containerRef.current,
      state,
    })
    viewRef.current = view

    if (autoFocus) {
      view.focus()
    }

    return () => {
      view.destroy()
      viewRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Apply theme updates without rebuilding the editor.
  useEffect(() => {
    const view = viewRef.current
    if (!view) return
    view.dispatch({
      effects: themeCompartmentRef.current.reconfigure(baseTheme),
    })
  }, [baseTheme])

  // Reflect external value changes (e.g. inserting a snippet from the sidebar).
  useEffect(() => {
    const view = viewRef.current
    if (!view) return
    const current = view.state.doc.toString()
    if (current === value) return
    view.dispatch({
      changes: { from: 0, insert: value, to: current.length },
    })
  }, [value])

  return (
    <div
      className="border-tertiary bg-primary rounded-md border"
      ref={containerRef}
      style={{ borderWidth: '0.5px' }}
    />
  )
}
