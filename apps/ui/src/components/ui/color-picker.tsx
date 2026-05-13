import { type KeyboardEvent, useEffect, useRef, useState } from 'react'

import { Check } from 'lucide-react'

import { useTheme } from '@/contexts/ThemeContext'
import { deriveChipColors, hexToRgb } from '@/lib/chip-colors'

interface Swatch {
  hex: string
  name: string
}

const SWATCHES: Swatch[] = [
  { hex: '#C86B5E', name: 'Clay' },
  { hex: '#D98847', name: 'Ember' },
  { hex: '#C9A227', name: 'Honey' },
  { hex: '#6B9A3F', name: 'Moss' },
  { hex: '#5A89C9', name: 'Dusk' },
  { hex: '#8C82D4', name: 'Lilac' },
  { hex: '#C96B97', name: 'Rose' },
  { hex: '#7A7873', name: 'Stone' },
]

interface ColorPickerProps {
  /** The label/name value previewed in the chip. Mirrors the name field above. */
  labelValue: string
  /** What kind of object this color labels (e.g. "environment", "project type"). */
  objectType: string
  onChange: (color: string) => void
  value: string
}

export function ColorPicker({
  labelValue,
  objectType,
  onChange,
  value,
}: ColorPickerProps) {
  const { isDarkMode } = useTheme()
  const [hexInput, setHexInput] = useState(value)
  const swatchRefs = useRef<Array<HTMLButtonElement | null>>([])
  const nativeColorRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setHexInput(value)
  }, [value])

  const normalized = value?.toUpperCase() ?? ''
  const selectedIdx = SWATCHES.findIndex(
    (s) => s.hex.toUpperCase() === normalized,
  )

  const commit = (hex: string) => {
    const upper = hex.toUpperCase()
    setHexInput(upper)
    onChange(upper)
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const currentIdx = selectedIdx >= 0 ? selectedIdx : 0
    let nextIdx = currentIdx
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
      nextIdx = (currentIdx + 1) % SWATCHES.length
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
      nextIdx = (currentIdx - 1 + SWATCHES.length) % SWATCHES.length
    } else if (e.key === ' ' || e.key === 'Enter') {
      e.preventDefault()
      commit(SWATCHES[currentIdx].hex)
      return
    } else {
      return
    }
    e.preventDefault()
    commit(SWATCHES[nextIdx].hex)
    swatchRefs.current[nextIdx]?.focus()
  }

  const isValidHex = /^#[0-9A-Fa-f]{6}$/.test(hexInput)
  const derived = isValidHex
    ? deriveChipColors(hexInput, isDarkMode)
    : deriveChipColors(value, isDarkMode)
  const swatchRgb = isValidHex ? hexToRgb(hexInput) : hexToRgb(value)
  // Chip bg is rgba at 20% alpha composited on the page surface (bg-tertiary).
  // Contrast must be measured against that effective color, not the saturated hex.
  const surface = isDarkMode
    ? { b: 0x13, g: 0x14, r: 0x14 }
    : { b: 0xf0, g: 0xf4, r: 0xf5 }
  const effectiveBg = swatchRgb
    ? {
        b: Math.round(swatchRgb.b * 0.2 + surface.b * 0.8),
        g: Math.round(swatchRgb.g * 0.2 + surface.g * 0.8),
        r: Math.round(swatchRgb.r * 0.2 + surface.r * 0.8),
      }
    : null
  const contrast =
    derived && effectiveBg
      ? contrastRatio(
          derived.fg,
          `rgb(${effectiveBg.r},${effectiveBg.g},${effectiveBg.b})`,
        )
      : null
  // WCAG AA minimum for small text (11.5-13px chip labels here).
  const MIN_TEXT_CONTRAST = 4.5
  const hasLowContrast =
    isValidHex && contrast !== null && contrast < MIN_TEXT_CONTRAST

  const previewText = labelValue.trim() || 'Label'

  const pipBackground = isValidHex ? hexInput : 'transparent'

  const hasPartialHex = hexInput.trim() !== '' && !isValidHex
  const statusLabel = !isValidHex
    ? hasPartialHex
      ? 'Invalid'
      : null
    : hasLowContrast
      ? 'Low contrast'
      : 'Valid'

  return (
    <div className="space-y-3">
      <label
        className="text-secondary mb-1.5 block text-sm"
        htmlFor="color-picker-swatches"
      >
        Label color
        <span className="text-tertiary ml-1 text-xs">
          · used on chips wherever this {objectType} appears
        </span>
      </label>

      <div className="bg-tertiary max-w-md rounded-md p-3.5">
        {/* Swatch radio group */}
        <div
          aria-label="Label color"
          className="grid grid-cols-8 gap-2"
          id="color-picker-swatches"
          onKeyDown={handleKeyDown}
          role="radiogroup"
        >
          {SWATCHES.map((s, i) => {
            const checked = selectedIdx === i
            return (
              <button
                aria-checked={checked}
                aria-label={`${s.name} · ${s.hex}`}
                className={`focus-visible:ring-info relative flex aspect-square items-center justify-center rounded-[10px] border-2 transition-transform hover:-translate-y-px focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none ${
                  checked ? 'border-primary' : 'border-transparent'
                }`}
                key={s.hex}
                onClick={() => commit(s.hex)}
                ref={(el) => {
                  swatchRefs.current[i] = el
                }}
                role="radio"
                style={{ backgroundColor: s.hex }}
                tabIndex={checked || (selectedIdx < 0 && i === 0) ? 0 : -1}
                title={`${s.name} · ${s.hex}`}
                type="button"
              >
                {checked && (
                  <Check
                    aria-hidden
                    className="size-3.5 text-white"
                    style={{ filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.3))' }}
                  />
                )}
              </button>
            )
          })}
        </div>

        {/* Swatch names */}
        <div className="mt-1.5 grid grid-cols-8 gap-2">
          {SWATCHES.map((s) => (
            <span
              className="text-tertiary text-center font-mono text-[10.5px]"
              key={s.hex}
            >
              {s.name}
            </span>
          ))}
        </div>

        {/* Divider */}
        <div className="text-tertiary my-4 flex items-center gap-2.5 text-[11.5px] font-medium tracking-wider uppercase">
          <span aria-hidden className="bg-tertiary h-px flex-1" />
          or custom hex
          <span aria-hidden className="bg-tertiary h-px flex-1" />
        </div>

        {/* Hex input group */}
        <div className="border-tertiary bg-primary focus-within:border-secondary flex items-center gap-1 rounded-md border p-1 transition-colors">
          <label
            aria-label="Open OS color picker"
            className="border-tertiary relative size-7 shrink-0 cursor-pointer rounded-md border"
            style={{ backgroundColor: pipBackground }}
          >
            <input
              className="absolute inset-0 size-full cursor-pointer opacity-0"
              onChange={(e) => commit(e.target.value)}
              ref={nativeColorRef}
              type="color"
              value={isValidHex ? hexInput : '#000000'}
            />
          </label>
          <input
            aria-label="Hex color"
            className="text-primary placeholder:text-tertiary flex-1 border-0 bg-transparent px-2 font-mono text-[13px] outline-none"
            maxLength={7}
            onChange={(e) => {
              const raw = e.target.value.toUpperCase()
              if (!/^$|^#[0-9A-F]{0,6}$/.test(raw)) return
              setHexInput(raw)
              if (raw === '' || /^#[0-9A-F]{6}$/.test(raw)) {
                onChange(raw)
              }
            }}
            placeholder="#C9A227"
            spellCheck={false}
            type="text"
            value={hexInput}
          />
          {statusLabel && (
            <span
              className={`mr-1 rounded px-2 py-1 text-[11px] font-medium ${
                hasPartialHex
                  ? 'bg-danger text-danger'
                  : hasLowContrast
                    ? 'bg-warning text-warning'
                    : 'bg-success text-success'
              }`}
              role="status"
            >
              {statusLabel}
            </span>
          )}
        </div>
      </div>

      {/* Preview */}
      {derived && (
        <div className="border-tertiary border-t border-dashed pt-4">
          <div className="text-tertiary mb-2.5 text-[11px] font-semibold tracking-wider uppercase">
            Preview · this label
          </div>
          <div className="flex flex-wrap items-center gap-2.5">
            <span
              className="inline-flex items-center rounded-[5px] px-2 text-[11.5px] font-medium"
              style={{
                backgroundColor: derived.bg,
                color: derived.fg,
                height: 22,
                letterSpacing: '0.02em',
              }}
            >
              {previewText}
            </span>
            <span
              className="inline-flex items-center rounded-[5px] px-2.5 text-[13px] font-medium"
              style={{
                backgroundColor: derived.bg,
                color: derived.fg,
                height: 26,
              }}
            >
              {previewText}
            </span>
            <span className="text-secondary inline-flex items-center gap-1.5 text-[13px]">
              <span
                aria-hidden
                className="inline-block size-2 rounded-full"
                style={{ backgroundColor: value }}
              />
              {previewText}
            </span>
          </div>
          <p className="text-tertiary mt-2 text-xs">
            Shows this label at the three sizes it appears across the product.
          </p>
        </div>
      )}
    </div>
  )
}

function contrastRatio(fg: string, bg: string): null | number {
  const f = parseRgb(fg)
  const b = parseRgb(bg)
  if (!f || !b) return null
  const L1 = relativeLuminance(f.r, f.g, f.b)
  const L2 = relativeLuminance(b.r, b.g, b.b)
  return (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05)
}

function parseRgb(color: string): null | { b: number; g: number; r: number } {
  if (color.startsWith('#')) return hexToRgb(color)
  const m = color.match(/\d+/g)
  if (!m || m.length < 3) return null
  return { b: +m[2], g: +m[1], r: +m[0] }
}

function relativeLuminance(r: number, g: number, b: number): number {
  const a = [r, g, b].map((v) => {
    const s = v / 255
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4)
  })
  return a[0] * 0.2126 + a[1] * 0.7152 + a[2] * 0.0722
}
