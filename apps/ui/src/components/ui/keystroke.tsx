const isMac = /macintosh|ipad|iphone/i.test(navigator.userAgent)

const keyGlyphs: Record<string, string> = {
  ArrowDown: '↓',
  ArrowLeft: '←',
  ArrowRight: '→',
  ArrowUp: '↑',
}

type KeystrokeProps = {
  className?: string
  /** Override platform detection (useful in tests) */
  isMac?: boolean
  /** e.g. "Ctrl+Shift+A" or "/" — uses Ctrl to mean Cmd on Mac */
  value: string
}

export function Keystroke({
  className,
  isMac: isMacProp,
  value,
}: KeystrokeProps) {
  const mac = isMacProp ?? isMac
  const glyphs: Record<string, string> = mac
    ? { alt: '⌥', ctrl: '⌘', shift: '⇧' }
    : { alt: 'Alt', ctrl: 'Ctrl', shift: 'Shift' }
  const keys = value.split('+')
  return (
    <span className={className}>
      {keys.map((key, i) => {
        const lower = key.trim().toLowerCase()
        const display = glyphs[lower] ?? keyGlyphs[key] ?? key
        return (
          <kbd
            className="border-muted-foreground/40 text-muted-foreground inline-flex items-center rounded border px-1 font-mono text-[10px] leading-none"
            key={i}
          >
            {display}
          </kbd>
        )
      })}
    </span>
  )
}
