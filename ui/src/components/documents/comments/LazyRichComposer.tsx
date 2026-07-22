import { lazy, Suspense } from 'react'

import { Sk } from '@/components/ui/skeleton'

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
        <div className="flex flex-col gap-2">
          <Sk h={32} r={4} w="100%" />
          <Sk h={88} r={4} w="100%" />
        </div>
      }
    >
      <RichCommentComposer {...props} />
    </Suspense>
  )
}
