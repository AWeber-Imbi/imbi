import type { CSSProperties, HTMLAttributes, ReactNode } from 'react'

import { cn } from '@/lib/utils'

interface SkProps {
  /** Amber variant, reserved for Imbot-generated content. */
  ai?: boolean
  /** Fully rounded (avatars, dots). */
  circle?: boolean
  className?: string
  /** Height — number (px) or any CSS length. Defaults to a text-line height. */
  h?: number | string
  /** Text-line proportions (rounded 4px, ~11px tall). */
  line?: boolean
  /** Border radius — number (px) or any CSS length. */
  r?: number | string
  style?: CSSProperties
  /** Width — number (px) or any CSS length/percentage. */
  w?: number | string
}

interface SkTextProps {
  ai?: boolean
  className?: string
  /** One width per line; the last is naturally short. */
  widths?: (number | string)[]
}

interface SwapProps {
  children: ReactNode
  className?: string
  /** Stagger reveals when several regions arrive together (ms). */
  delay?: number
  /** When true, reveal `children`; otherwise show `skeleton`. */
  ready: boolean
  skeleton: ReactNode
}

/**
 * A sized placeholder block that mirrors the shape of real content with a slow
 * low-contrast sweep. Decorative — kept out of the accessibility tree.
 */
export function Sk({
  ai,
  circle,
  className,
  h = 11,
  line,
  r,
  style = {},
  w,
}: SkProps) {
  return (
    <div
      aria-hidden
      className={cn('sk', ai && 'sk-ai', line && 'sk-line', className)}
      style={{
        borderRadius: circle ? '9999px' : r,
        height: h,
        width: w,
        ...style,
      }}
    />
  )
}

/**
 * Legacy loading placeholder block. Apply size/shape via className (h-*, w-*,
 * rounded-*). Retained so existing call sites keep working while surfaces
 * migrate to the `Sk`/`SkText`/`Swap` skeleton primitives below.
 *
 * @deprecated Prefer `Sk` for footprint-matched skeletons (sweep, not pulse).
 */
export function Skeleton({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('animate-pulse rounded bg-tertiary/30', className)}
      {...props}
    />
  )
}

/** A paragraph of skeleton text lines. */
export function SkText({
  ai,
  className,
  widths = ['100%', '92%', '70%'],
}: SkTextProps) {
  return (
    <div className={cn('flex flex-col gap-2', className)}>
      {widths.map((w, i) => (
        <Sk ai={ai} key={i} line w={w} />
      ))}
    </div>
  )
}

/**
 * Shows `skeleton` until `ready`, then reveals `children` with a fade+lift.
 * The region container carries `aria-busy` while loading (cleared on data) so
 * call sites get the screen-reader convention for free.
 */
export function Swap({
  children,
  className,
  delay = 0,
  ready,
  skeleton,
}: SwapProps) {
  if (!ready) {
    return (
      <div aria-busy className={className}>
        {skeleton}
      </div>
    )
  }
  return (
    <div
      className={cn('reveal', className)}
      style={delay ? { animationDelay: `${delay}ms` } : undefined}
    >
      {children}
    </div>
  )
}
