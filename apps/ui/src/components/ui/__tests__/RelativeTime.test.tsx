import { describe, expect, it } from 'vitest'

import { render, screen } from '@/test/utils'

import { RelativeTime } from '../RelativeTime'

const ISO = '2026-01-01T00:00:00Z'

describe('RelativeTime', () => {
  describe('null/undefined value', () => {
    it('renders em-dash for null', () => {
      render(<RelativeTime value={null} />)
      expect(screen.getByText('—')).toBeInTheDocument()
    })

    it('renders em-dash when value is omitted', () => {
      render(<RelativeTime />)
      expect(screen.getByText('—')).toBeInTheDocument()
    })
  })

  describe('semantic markup', () => {
    it('renders a <time> element with a dateTime attribute', () => {
      render(<RelativeTime value={ISO} />)
      const el = document.querySelector('time')
      expect(el).not.toBeNull()
      expect(el!.getAttribute('dateTime')).toBe(ISO)
    })

    it('passes className to the <time> element', () => {
      render(<RelativeTime className="text-xs text-red-500" value={ISO} />)
      const el = document.querySelector('time')
      expect(el!.className).toContain('text-xs')
      expect(el!.className).toContain('text-red-500')
    })
  })

  describe('variant output shape', () => {
    it('narrow: renders compact format without "ago"', () => {
      render(<RelativeTime tooltip={false} value={ISO} variant="narrow" />)
      const el = document.querySelector('time')!
      // Value is in the past so it should be a compact token like "5mo", "1y" etc.
      expect(el.textContent).toMatch(/^\d+(m|h|d|w|mo|y)$/)
    })

    it('short (default): renders "X ago" format', () => {
      render(<RelativeTime tooltip={false} value={ISO} />)
      const el = document.querySelector('time')!
      expect(el.textContent).toMatch(/(ago|just now)/)
    })

    it('long: renders verbose "about X ago" format', () => {
      render(<RelativeTime tooltip={false} value={ISO} variant="long" />)
      const el = document.querySelector('time')!
      // date-fns formatDistanceToNow with addSuffix
      expect(el.textContent).toMatch(/ago/)
    })
  })

  describe('tooltip={false}', () => {
    it('sets title attribute to the absolute timestamp', () => {
      render(<RelativeTime tooltip={false} value={ISO} />)
      const el = document.querySelector('time')!
      const title = el.getAttribute('title')
      expect(title).not.toBeNull()
      expect(title).toMatch(/2026/)
      expect(title).toMatch(/Jan/)
    })

    it('does not render a TooltipProvider', () => {
      const { container } = render(<RelativeTime tooltip={false} value={ISO} />)
      // TooltipProvider adds no DOM node of its own, but the time element
      // should be the direct root with no Radix portal siblings.
      expect(container.firstChild?.nodeName).toBe('TIME')
    })
  })

  describe('tooltip={true} (default)', () => {
    it('does not set a title attribute on the <time> element', () => {
      render(<RelativeTime value={ISO} />)
      const el = document.querySelector('time')!
      expect(el.getAttribute('title')).toBeNull()
    })
  })
})
