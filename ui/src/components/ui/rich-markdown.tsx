import { useMemo } from 'react'

import Markdown, { type Components, type Options } from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { DeferredImage } from '@/components/ui/deferred-image'
import { FrontmatterTable } from '@/components/ui/frontmatter-table'
import { useProjectRepoUrl } from '@/contexts/ProjectRepoContext'
import { splitFrontmatter } from '@/lib/frontmatter'
import { remarkGithubRefs } from '@/lib/github-refs'

interface RichMarkdownProps {
  children: string
  /**
   * Load images only on a click, in the body and the frontmatter. Use it
   * for text an agent or another untrusted author wrote: an image loads
   * with no click, so its URL can carry data out of the page.
   */
  deferImages?: boolean
}

const COMPONENTS: Components = {
  a: ({ node: _node, ...props }) => (
    <a {...props} rel="noopener noreferrer" target="_blank" />
  ),
}

const DEFERRED_IMAGES: Components = {
  ...COMPONENTS,
  img: ({ alt, src }) => (
    <DeferredImage alt={alt} src={typeof src === 'string' ? src : undefined} />
  ),
}

/**
 * GFM markdown with links opening in a new tab and, under a project page
 * whose GitHub repository is known, ``#N`` references linked to their
 * issue/PR. A leading YAML frontmatter block renders as a table. Callers
 * own the surrounding ``document-markdown`` wrapper.
 */
export function RichMarkdown({
  children,
  deferImages = false,
}: RichMarkdownProps) {
  const repoUrl = useProjectRepoUrl()
  const remarkPlugins = useMemo<Options['remarkPlugins']>(
    () =>
      repoUrl ? [remarkGfm, [remarkGithubRefs, { repoUrl }]] : [remarkGfm],
    [repoUrl],
  )
  const { body, meta } = splitFrontmatter(children)
  return (
    <>
      {meta && <FrontmatterTable deferImages={deferImages} meta={meta} />}
      <Markdown
        components={deferImages ? DEFERRED_IMAGES : COMPONENTS}
        remarkPlugins={remarkPlugins}
      >
        {body}
      </Markdown>
    </>
  )
}
