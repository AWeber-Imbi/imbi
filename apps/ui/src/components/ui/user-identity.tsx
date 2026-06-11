import { useEffect, useState } from 'react'

import { Link } from 'react-router-dom'

import { Bot } from 'lucide-react'

import { cn } from '@/lib/utils'

import { useGravatarUrl } from './gravatar'

type Size = 'floating' | 'large' | 'medium' | 'small'

interface SizeSpec {
  av: number
  font: number
  gap: number
  sub: boolean
  weight: number
}

interface UserIdentityProps {
  className?: string
  /** Shown as a subtitle at medium/large sizes (mono when it looks like an email). */
  email?: null | string
  /**
   * Explicit avatar photo. When omitted, a Gravatar is derived from `email`.
   * Either way, a missing or broken image falls back to initials.
   */
  image?: null | string
  kind?: 'bot' | 'user'
  /**
   * Link the chip to the user's profile (`/users/:email`) when an email is
   * known and the actor is a person. Defaults to true.
   */
  linkToProfile?: boolean
  /** Display name; drives the initials and the hashed fallback color. */
  name: null | string
  size?: Size
}

const BOT_PATTERN =
  /(\[bot\]|\bbot\b|-bot\b|github-actions|\bactions\b|automation|\bservice\b)/i

// The eight Imbi label-palette hues; an actor's initials avatar gets a stable
// one picked by hashing the name.
const PALETTE = [
  '#C86B5E',
  '#D98847',
  '#C9A227',
  '#6B9A3F',
  '#5A89C9',
  '#8C82D4',
  '#C96B97',
  '#7A7873',
]

const SIZES: Record<Size, SizeSpec> = {
  floating: { av: 24, font: 14, gap: 8, sub: false, weight: 600 },
  large: { av: 44, font: 17, gap: 12, sub: true, weight: 600 },
  medium: { av: 28, font: 14, gap: 9, sub: true, weight: 500 },
  small: { av: 20, font: 13.5, gap: 7, sub: false, weight: 500 },
}

/** Whether an actor login/name reads as a bot or automation account. */
export function isBotActor(name: null | string): boolean {
  return name != null && BOT_PATTERN.test(name)
}

/**
 * Canonical identity widget — a person or actor anywhere they appear in Imbi
 * (deploy attribution, ops-log rows, currently-running footers, activity
 * feeds). Avatar resolution: a photo when one loads, a bot glyph for
 * automation actors, otherwise initials on a name-hashed tint.
 */
export function UserIdentity({
  className,
  email,
  image,
  kind = 'user',
  linkToProfile = true,
  name,
  size = 'medium',
}: UserIdentityProps) {
  const s = SIZES[size]
  const isBot = kind === 'bot'
  const profileEmail = !isBot && linkToProfile && email ? email : null
  // Request at 2× for retina; `d=404` makes a missing Gravatar error out so
  // the <img> onError handler falls back to the initials chip.
  const gravatarUrl = useGravatarUrl(email ?? '', s.av * 2, '404')
  const explicitImage = image != null && image !== '' ? image : null
  const candidateImage = explicitImage ?? (!isBot && email ? gravatarUrl : null)

  const body = (
    <>
      <IdentityAvatar
        av={s.av}
        candidateImage={candidateImage}
        isBot={isBot}
        name={name}
      />
      <IdentityText email={email} name={name} size={size} spec={s} />
    </>
  )

  if (profileEmail) {
    return (
      <Link
        className={cn(
          'inline-flex min-w-0 items-center hover:underline',
          className,
        )}
        onClick={(event) => event.stopPropagation()}
        style={{ gap: s.gap }}
        title={name ?? profileEmail}
        to={`/users/${encodeURIComponent(profileEmail)}`}
      >
        {body}
      </Link>
    )
  }

  return (
    <span
      className={cn('inline-flex min-w-0 items-center', className)}
      style={{ gap: s.gap }}
    >
      {body}
    </span>
  )
}

function colorFor(name: null | string): string {
  return PALETTE[hashStr(name || '?') % PALETTE.length]
}

function darken(hex: string, f: number): string {
  const n = parseInt(hex.slice(1), 16)
  const r = (n >> 16) & 255
  const g = (n >> 8) & 255
  const b = n & 255
  return `rgb(${Math.round(r * f)}, ${Math.round(g * f)}, ${Math.round(b * f)})`
}

function hashStr(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) {
    h = (h << 5) - h + s.charCodeAt(i)
    h |= 0
  }
  return Math.abs(h)
}

function IdentityAvatar({
  av,
  candidateImage,
  isBot,
  name,
}: {
  av: number
  candidateImage: null | string
  isBot: boolean
  name: null | string
}) {
  const [imgFailed, setImgFailed] = useState(false)
  useEffect(() => {
    setImgFailed(false)
  }, [candidateImage, isBot])
  const tint = colorFor(name)
  const showImage = !isBot && candidateImage != null && !imgFailed
  const style: React.CSSProperties = { height: av, width: av }
  if (isBot) {
    style.boxShadow = 'inset 0 0 0 1px var(--color-border)'
  } else if (!showImage) {
    style.backgroundColor = `${tint}33`
  }
  return (
    <span
      className={cn(
        'relative inline-flex flex-none items-center justify-center overflow-hidden rounded-full',
        isBot ? 'bg-secondary text-secondary' : 'bg-secondary',
      )}
      style={style}
    >
      {isBot ? (
        <Bot size={Math.round(av * 0.58)} />
      ) : showImage ? (
        <img
          alt={name ?? ''}
          className="block size-full object-cover"
          onError={() => setImgFailed(true)}
          referrerPolicy="no-referrer"
          src={candidateImage as string}
        />
      ) : (
        <span
          className="leading-none font-semibold tracking-tight uppercase"
          style={{ color: darken(tint, 0.55), fontSize: Math.round(av * 0.42) }}
        >
          {initialsOf(name)}
        </span>
      )}
    </span>
  )
}

function IdentityText({
  email,
  name,
  size,
  spec,
}: {
  email?: null | string
  name: null | string
  size: Size
  spec: SizeSpec
}) {
  return (
    <span className="flex min-w-0 flex-col">
      <span
        className="text-primary truncate"
        style={{
          fontSize: spec.font,
          fontWeight: spec.weight,
          lineHeight: spec.sub ? 1.25 : 1,
        }}
      >
        {name || 'Unknown'}
      </span>
      {spec.sub && email ? (
        <span
          className={cn(
            'mt-0.5 truncate text-tertiary',
            email.includes('@') ? 'font-mono' : 'font-sans',
          )}
          style={{ fontSize: size === 'large' ? 13 : 12 }}
        >
          {email}
        </span>
      ) : null}
    </span>
  )
}

function initialsOf(name: null | string): string {
  if (!name) return '?'
  const parts = name
    .trim()
    .split(/[\s._-]+/)
    .filter(Boolean)
  if (parts.length >= 2) {
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
  }
  return (parts[0]?.[0] ?? '?').toUpperCase()
}
