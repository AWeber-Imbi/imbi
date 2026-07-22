import { createElement } from 'react'

import type { IconComponent } from '@/lib/icon-registry'

export function createImgComponent(url: string): IconComponent {
  const ImgIcon: IconComponent = (props) => {
    const { className, height, width, ...rest } = props as Record<
      string,
      unknown
    >
    return createElement('img', {
      alt: '',
      className,
      height: height ?? 16,
      src: url,
      width: width ?? 16,
      ...rest,
    })
  }
  return ImgIcon
}

export function encodeSvgToDataUrl(markup: string): string {
  return `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(markup)))}`
}

export function toPascalCase(str: string): string {
  return str
    .split('-')
    .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
    .join('')
}

// Phosphor and Tabler export React.forwardRef wrappers, not plain functions.
// Using $$typeof is required because typeof forwardRef component === 'object'.
const REACT_FORWARD_REF = Symbol.for('react.forward_ref')

export function isForwardRefComponent(v: unknown): v is IconComponent {
  return (
    v !== null &&
    typeof v === 'object' &&
    (v as Record<string, unknown>)['$$typeof'] === REACT_FORWARD_REF
  )
}
