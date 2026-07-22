/* eslint-disable react-refresh/only-export-components */
import { useEffect, useState } from 'react'

import { Link } from 'react-router-dom'

import { Bot } from 'lucide-react'

import { swatchForName } from '@/lib/chip-colors'
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
  /** Login/handle for remote actors with no known email (e.g. `performed_by`). */
  actor?: null | string
  className?: string
  /** Explicit display name; wins over all resolution. */
  displayName?: null | string
  /** email → display_name lookup for row lists (from useUserDisplayNames). */
  displayNames?: Map<string, string>
  /** Imbi user email — drives Gravatar, profile link, and local-part fallback. */
  email?: null | string
  /** Avatar-only mode: render the avatar without the name/secondary text. */
  hideName?: boolean
  /**
   * Explicit avatar photo (e.g. a service account's avatar_url). When omitted,
   * a Gravatar is derived from `email`. Either way a missing or broken image
   * falls back to initials.
   */
  image?: null | string
  /** Defaults to auto-detect via BOT_PATTERN on the actor/name. */
  kind?: 'bot' | 'user'
  /**
   * Link the chip to the user's profile (`/users/:email`) when an email is
   * known and the actor is a person. Defaults to true.
   */
  linkToProfile?: boolean
  /** Secondary line for medium/large; defaults to `email` when present. */
  secondary?: null | string
  size?: Size
  /** Tooltip override; defaults to the resolved name. */
  title?: string
}

const BOT_PATTERN =
  /(\[bot\]|\bbot\b|-bot\b|github-actions|\bactions\b|automation|\bservice\b)/i

const SIZES: Record<Size, SizeSpec> = {
  floating: { av: 24, font: 14, gap: 8, sub: false, weight: 600 },
  large: { av: 44, font: 17, gap: 12, sub: true, weight: 600 },
  medium: { av: 28, font: 14, gap: 9, sub: true, weight: 500 },
  small: { av: 20, font: 13.5, gap: 7, sub: false, weight: 500 },
}

/** Whether an actor login/name reads as a bot or automation account. */
export function isBotActor(value: null | string | undefined): boolean {
  return value != null && BOT_PATTERN.test(value)
}

/**
 * Canonical identity widget — a person or actor anywhere they appear in Imbi
 * (deploy attribution, ops-log rows, currently-running footers, activity
 * feeds). Resolves the display name from `displayName`/`displayNames`/`email`/
 * `actor`, then renders an avatar: a photo when one loads, a bot glyph for
 * automation actors, otherwise initials on a name-hashed tint.
 */
// fallow-ignore-next-line complexity
export function UserIdentity({
  actor,
  className,
  displayName,
  displayNames,
  email,
  hideName = false,
  image,
  kind,
  linkToProfile = true,
  secondary,
  size = 'medium',
  title,
}: UserIdentityProps) {
  const s = SIZES[size]
  const name = resolveName(displayName, displayNames, email, actor)
  const isBot = kind != null ? kind === 'bot' : isBotActor(actor ?? name)
  const profileEmail = !isBot && linkToProfile && email ? email : null
  // Request at 2× for retina; `d=404` makes a missing Gravatar error out so
  // the <img> onError handler falls back to the initials chip.
  const gravatarUrl = useGravatarUrl(email ?? '', s.av * 2, '404')
  const explicitImage = image != null && image !== '' ? image : null
  const candidateImage = explicitImage ?? (!isBot && email ? gravatarUrl : null)
  const tooltip = title ?? name ?? email ?? undefined

  const body = (
    <>
      <IdentityAvatar
        av={s.av}
        candidateImage={candidateImage}
        isBot={isBot}
        name={name}
      />
      {hideName ? null : (
        <IdentityText
          email={email}
          name={name}
          secondary={secondary}
          size={size}
          spec={s}
        />
      )}
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
        style={{ gap: hideName ? 0 : s.gap }}
        title={tooltip}
        to={`/users/${encodeURIComponent(profileEmail)}`}
      >
        {body}
      </Link>
    )
  }

  return (
    <span
      className={cn('inline-flex min-w-0 items-center', className)}
      style={{ gap: hideName ? 0 : s.gap }}
      title={tooltip}
    >
      {body}
    </span>
  )
}

function darken(hex: string, f: number): string {
  const n = parseInt(hex.slice(1), 16)
  const r = (n >> 16) & 255
  const g = (n >> 8) & 255
  const b = n & 255
  return `rgb(${Math.round(r * f)}, ${Math.round(g * f)}, ${Math.round(b * f)})`
}

// fallow-ignore-next-line complexity
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
  const tint = swatchForName(name || '?')
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
  secondary,
  size,
  spec,
}: {
  email?: null | string
  name: null | string
  secondary?: null | string
  size: Size
  spec: SizeSpec
}) {
  const sub = secondary ?? email
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
      {spec.sub && sub ? (
        <span
          className={cn(
            'mt-0.5 truncate text-tertiary',
            sub.includes('@') ? 'font-mono' : 'font-sans',
          )}
          style={{ fontSize: size === 'large' ? 13 : 12 }}
        >
          {sub}
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

/** Resolve the rendered display name from the available identity fields. */
function resolveName(
  displayName: null | string | undefined,
  displayNames: Map<string, string> | undefined,
  email: null | string | undefined,
  actor: null | string | undefined,
): null | string {
  if (displayName) return displayName
  const mapped = email ? displayNames?.get(email) : undefined
  if (mapped) return mapped
  const local = email ? email.split('@')[0] : null
  if (local) return local
  return actor ?? null
}
