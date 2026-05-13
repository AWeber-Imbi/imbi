import { type ReactNode } from 'react'

import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'

import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { useAdminNav } from '../useAdminNav'

let latestPath = '/'

function LocationProbe() {
  const loc = useLocation()
  latestPath = loc.pathname
  return null
}

function pressKey(
  key: string,
  init: Partial<KeyboardEventInit> & {
    target?: EventTarget
  } = {},
) {
  const { target, ...rest } = init
  const event = new KeyboardEvent('keydown', {
    bubbles: true,
    cancelable: true,
    key,
    ...rest,
  })
  if (target) {
    target.dispatchEvent(event)
  } else {
    window.dispatchEvent(event)
  }
  return event
}

function wrap(initialPath: string) {
  return ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={[initialPath]}>
      <LocationProbe />
      <Routes>
        <Route
          element={<>{children}</>}
          path="/admin/:section?/:slug?/:action?"
        />
      </Routes>
    </MemoryRouter>
  )
}

describe('useAdminNav hotkeys', () => {
  beforeEach(() => {
    latestPath = '/'
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('pressing "e" on a detail view navigates to edit', () => {
    const { result } = renderHook(() => useAdminNav(), {
      wrapper: wrap('/admin/third-party-services/sonarqube'),
    })

    expect(result.current.viewMode).toBe('detail')
    expect(result.current.slug).toBe('sonarqube')

    act(() => {
      pressKey('e')
    })

    expect(latestPath).toBe('/admin/third-party-services/sonarqube/edit')
  })

  it('pressing Escape on an edit view navigates to the list', () => {
    renderHook(() => useAdminNav(), {
      wrapper: wrap('/admin/third-party-services/sonarqube/edit'),
    })

    act(() => {
      pressKey('Escape')
    })

    expect(latestPath).toBe('/admin/third-party-services')
  })

  it('pressing Escape on a create view navigates to the list', () => {
    renderHook(() => useAdminNav(), {
      wrapper: wrap('/admin/third-party-services/new'),
    })

    act(() => {
      pressKey('Escape')
    })

    expect(latestPath).toBe('/admin/third-party-services')
  })

  it('does not navigate when "e" is pressed in a list view', () => {
    renderHook(() => useAdminNav(), {
      wrapper: wrap('/admin/third-party-services'),
    })

    act(() => {
      pressKey('e')
    })

    expect(latestPath).toBe('/admin/third-party-services')
  })

  it('does not navigate when "e" is pressed inside an input', () => {
    renderHook(() => useAdminNav(), {
      wrapper: wrap('/admin/third-party-services/sonarqube'),
    })

    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()

    act(() => {
      pressKey('e', { target: input })
    })

    expect(latestPath).toBe('/admin/third-party-services/sonarqube')
  })

  it('does not navigate when "e" is pressed inside a textarea', () => {
    renderHook(() => useAdminNav(), {
      wrapper: wrap('/admin/third-party-services/sonarqube'),
    })

    const textarea = document.createElement('textarea')
    document.body.appendChild(textarea)
    textarea.focus()

    act(() => {
      pressKey('e', { target: textarea })
    })

    expect(latestPath).toBe('/admin/third-party-services/sonarqube')
  })

  it('does not navigate when "e" is pressed in a contenteditable element', () => {
    renderHook(() => useAdminNav(), {
      wrapper: wrap('/admin/third-party-services/sonarqube'),
    })

    const div = document.createElement('div')
    div.setAttribute('contenteditable', 'true')
    document.body.appendChild(div)
    div.focus()

    act(() => {
      pressKey('e', { target: div })
    })

    expect(latestPath).toBe('/admin/third-party-services/sonarqube')
  })

  it('skips hotkey when a modifier key is held', () => {
    renderHook(() => useAdminNav(), {
      wrapper: wrap('/admin/third-party-services/sonarqube'),
    })

    act(() => {
      pressKey('e', { metaKey: true })
    })

    expect(latestPath).toBe('/admin/third-party-services/sonarqube')
  })

  it('skips hotkey when an overlay (Radix data-state="open") is present', () => {
    renderHook(() => useAdminNav(), {
      wrapper: wrap('/admin/third-party-services/sonarqube'),
    })

    const dialog = document.createElement('div')
    dialog.setAttribute('role', 'dialog')
    dialog.setAttribute('data-state', 'open')
    document.body.appendChild(dialog)

    act(() => {
      pressKey('e')
    })

    expect(latestPath).toBe('/admin/third-party-services/sonarqube')
  })

  it('skips hotkey when the event was already handled', () => {
    renderHook(() => useAdminNav(), {
      wrapper: wrap('/admin/third-party-services/sonarqube'),
    })

    act(() => {
      const consumer = (e: Event) => e.preventDefault()
      window.addEventListener('keydown', consumer, { capture: true })
      pressKey('e')
      window.removeEventListener('keydown', consumer, { capture: true })
    })

    expect(latestPath).toBe('/admin/third-party-services/sonarqube')
  })

  it('does not act on Escape from a detail view', () => {
    renderHook(() => useAdminNav(), {
      wrapper: wrap('/admin/third-party-services/sonarqube'),
    })

    act(() => {
      pressKey('Escape')
    })

    expect(latestPath).toBe('/admin/third-party-services/sonarqube')
  })
})
