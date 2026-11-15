import { type CSSProperties, useLayoutEffect, useRef } from 'react'

import { SKIP_HIGHLIGHT } from './taskSearch'

/**
 * The text of a row the virtualizer does not render, hidden until the
 * browser's find (Cmd/Ctrl+F) matches it. React has no `until-found`
 * value for `hidden` yet, so it is set on the element directly.
 */
export function FindStub({
  index,
  onFound,
  style,
  text,
}: {
  index: number
  onFound: (index: number) => void
  style?: CSSProperties
  text: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    el.setAttribute('hidden', 'until-found')
    const found = () => onFound(index)
    el.addEventListener('beforematch', found)
    return () => el.removeEventListener('beforematch', found)
  }, [index, onFound])
  return (
    <div
      className="whitespace-pre-wrap"
      hidden
      ref={ref}
      style={style}
      {...{ [SKIP_HIGHLIGHT]: '' }}
    >
      {text}
    </div>
  )
}
