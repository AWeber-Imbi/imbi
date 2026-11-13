import { MemoryRouter } from 'react-router-dom'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  createEvent,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getComponentUsage, searchComponents } from '@/api/endpoints'

import { PackageUsageReport } from '../PackageUsageReport'

vi.mock('@/api/endpoints', () => ({
  getComponentUsage: vi.fn(),
  searchComponents: vi.fn(),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ user: { is_admin: false, permissions: [] } }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/components/packages/useComponentGovernance', () => ({
  useComponentGovernance: () => ({
    addNote: vi.fn(),
    isPending: false,
    recordAdvisory: vi.fn(),
    setStatus: vi.fn(),
  }),
}))

const HIT = {
  ecosystem: 'npm',
  id: 'cmp_1',
  name: 'api-clients',
  project_count: 47,
  purl_name: 'pkg:npm/%40aw-int/api-clients',
  version_count: 8,
}

const ALPHA = { ecosystem: 'npm', id: 'cmp_a', purl_name: 'pkg:npm/alpha' }
const BETA = { ecosystem: 'npm', id: 'cmp_b', purl_name: 'pkg:npm/beta' }

const usageOf = (pkg: typeof ALPHA) => ({
  ...pkg,
  deployed_version_count: 0,
  name: pkg.purl_name,
  project_count: 0,
  version_count: 0,
  versions: [],
  vulnerable_project_count: 0,
})

function renderReport() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <PackageUsageReport />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(searchComponents).mockImplementation((_org, params) =>
    Promise.resolve({
      data: params?.q ? [HIT] : [],
      ecosystem_totals: { npm: 1 },
      total: 1,
    }),
  )
  vi.mocked(getComponentUsage).mockReturnValue(new Promise(() => undefined))
})

describe('PackageUsageReport search', () => {
  it('opens the highlighted match with the arrow keys and Enter', async () => {
    renderReport()
    const input = screen.getByRole('combobox')
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: 'api-clients' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    const option = await screen.findByRole('option', { name: /api-clients/ })
    expect(option).toHaveAttribute('aria-selected', 'false')
    expect(input).not.toHaveAttribute('aria-activedescendant')

    fireEvent.keyDown(input, { key: 'ArrowDown' })
    expect(option).toHaveAttribute('aria-selected', 'true')
    expect(input).toHaveAttribute('aria-activedescendant', option.id)

    // Enter while a row is highlighted opens it instead of re-searching.
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() =>
      expect(getComponentUsage).toHaveBeenCalledWith(
        'acme',
        'cmp_1',
        expect.anything(),
      ),
    )
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('submits the typed term when no match is highlighted', async () => {
    renderReport()
    const input = screen.getByRole('combobox')
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: 'api-clients' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await screen.findByRole('option', { name: /api-clients/ })

    // Down then up lands back on "nothing highlighted", so Enter is a
    // search again, not a selection.
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'ArrowUp' })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(getComponentUsage).not.toHaveBeenCalled()
    expect(screen.getByRole('listbox')).toBeInTheDocument()
  })

  it('keeps the match list open through a Safari click', async () => {
    renderReport()
    const input = screen.getByRole('combobox')
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: 'api-clients' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    const option = await screen.findByRole('option', { name: /api-clients/ })

    // Safari does not focus a button on click, so the input's blur
    // arrives with no relatedTarget. The list must keep focus in the
    // input rather than unmount the option under the pointer.
    const mouseDown = createEvent.mouseDown(option)
    fireEvent(option, mouseDown)
    expect(mouseDown.defaultPrevented).toBe(true)

    fireEvent.click(option)
    await waitFor(() =>
      expect(getComponentUsage).toHaveBeenCalledWith(
        'acme',
        'cmp_1',
        expect.anything(),
      ),
    )
  })

  it('reopens the list when the still-focused input is clicked', async () => {
    renderReport()
    const input = screen.getByRole('combobox')
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: 'api-clients' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    const option = await screen.findByRole('option', { name: /api-clients/ })

    // The option click keeps focus in the input, so there is no focus
    // event to reopen on — the click itself has to do it.
    fireEvent.click(option)
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    fireEvent.click(input)
    expect(screen.getByRole('listbox')).toBeInTheDocument()
  })

  it('drops the highlight when the recents reorder underneath it', async () => {
    // The shared setup stubs localStorage with a no-op mock, so seed
    // the recents through the read rather than a write.
    vi.spyOn(localStorage, 'getItem').mockReturnValueOnce(
      JSON.stringify([ALPHA, BETA]),
    )
    vi.mocked(getComponentUsage).mockImplementation((_org, id) =>
      Promise.resolve(usageOf(id === BETA.id ? BETA : ALPHA)),
    )
    renderReport()
    const input = screen.getByRole('combobox')
    fireEvent.focus(input)
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    expect(screen.getByRole('option', { name: /beta/ })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    fireEvent.keyDown(input, { key: 'Enter' })

    // Opening beta moves it to the front of the recents. The count is
    // unchanged, so a count-keyed reset would leave index 1 — now
    // alpha — highlighted, and Enter would open the wrong package.
    fireEvent.click(input)
    await waitFor(() =>
      expect(screen.getAllByRole('option').map((el) => el.textContent)).toEqual(
        [expect.stringContaining('beta'), expect.stringContaining('alpha')],
      ),
    )
    expect(input).not.toHaveAttribute('aria-activedescendant')
    for (const el of screen.getAllByRole('option')) {
      expect(el).toHaveAttribute('aria-selected', 'false')
    }
  })
})
