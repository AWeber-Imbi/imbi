import { lazy, Suspense } from 'react'

import type { RichCommentComposerProps } from './RichCommentComposer'

// The type import above is erased at build time, so this module does not pull
// the heavy Lexical bundle in eagerly — only the dynamic import() below does.
const RichCommentComposer = lazy(() =>
  import('./RichCommentComposer').then((m) => ({
    default: m.RichCommentComposer,
  })),
)

/**
 * Lazy-loads the mdx-editor composer so the Lexical bundle is fetched only
 * when a composer actually mounts. Drop-in for any comment input.
 */
export function LazyRichComposer(props: RichCommentComposerProps) {
  return (
    <Suspense
      fallback={
        <div className="text-tertiary text-[13px]">Loading editor…</div>
      }
    >
      <RichCommentComposer {...props} />
    </Suspense>
  )
}
