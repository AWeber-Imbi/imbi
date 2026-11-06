import { useState } from 'react'

import { ImageIcon } from 'lucide-react'

interface DeferredImageProps {
  alt?: string
  src?: string
}

/**
 * An image that loads only when the reader asks. Use it for markdown
 * from an agent or another untrusted author: an image that loads with
 * no click can carry data out of the page in its URL.
 */
export function DeferredImage({ alt, src }: DeferredImageProps) {
  const [shown, setShown] = useState(false)
  const label = alt || src || 'image'
  return (
    <span className="inline-flex max-w-full flex-col items-start gap-1">
      <button
        aria-expanded={shown}
        className="text-info inline-flex items-center gap-1 text-xs hover:underline"
        onClick={() => setShown(!shown)}
        title={src}
        type="button"
      >
        <ImageIcon className="size-3.5 shrink-0" />
        {shown ? 'Hide image' : `Show image: ${label}`}
      </button>
      {shown && src && <img alt={alt} className="max-w-full" src={src} />}
    </span>
  )
}
