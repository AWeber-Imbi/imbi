import { fireEvent } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { render, screen } from '@/test/utils'

import { UserIdentity } from '../user-identity'

describe('UserIdentity name resolution', () => {
  it('prefers an explicit displayName over everything', () => {
    const names = new Map([['jane@example.com', 'Mapped Jane']])
    render(
      <UserIdentity
        actor="janed"
        displayName="Jane Doe"
        displayNames={names}
        email="jane@example.com"
      />,
    )
    expect(screen.getByText('Jane Doe')).toBeInTheDocument()
  })

  it('falls back to the displayNames map entry for the email', () => {
    const names = new Map([['jane@example.com', 'Mapped Jane']])
    render(<UserIdentity displayNames={names} email="jane@example.com" />)
    expect(screen.getByText('Mapped Jane')).toBeInTheDocument()
  })

  it('falls back to the email local-part when nothing else resolves', () => {
    render(<UserIdentity email="kevin.vance@example.com" />)
    expect(screen.getByText('kevin.vance')).toBeInTheDocument()
  })

  it('falls back to the actor login when there is no email', () => {
    render(<UserIdentity actor="edl" />)
    expect(screen.getByText('edl')).toBeInTheDocument()
  })

  it('renders "Unknown" when no identity is provided', () => {
    render(<UserIdentity />)
    expect(screen.getByText('Unknown')).toBeInTheDocument()
  })
})

describe('UserIdentity initials fallback', () => {
  it('uses first + last initials for multi-part names', () => {
    render(<UserIdentity displayName="Jane Doe" />)
    expect(screen.getByText('JD')).toBeInTheDocument()
  })

  it('uses a single initial for one-word names', () => {
    render(<UserIdentity displayName="Madonna" />)
    expect(screen.getByText('M')).toBeInTheDocument()
  })

  it('splits on dots and underscores', () => {
    render(<UserIdentity actor="kevin.vance" />)
    expect(screen.getByText('KV')).toBeInTheDocument()
  })

  it('renders a deterministic, stable tint for a given name', () => {
    render(
      <>
        <UserIdentity displayName="Jane Doe" />
        <UserIdentity displayName="Jane Doe" />
      </>,
    )
    const [a, b] = screen.getAllByText('JD')
    expect(a.getAttribute('style')).toContain('color')
    expect(a.getAttribute('style')).toBe(b.getAttribute('style'))
  })
})

describe('UserIdentity avatar resolution', () => {
  it('requests a Gravatar with d=404 so missing avatars error out', () => {
    const { container } = render(<UserIdentity email="jane@example.com" />)
    const img = container.querySelector('img')
    expect(img).not.toBeNull()
    expect(img?.getAttribute('src')).toContain('d=404')
  })

  it('falls back to initials when the avatar image fails to load', () => {
    const { container } = render(
      <UserIdentity displayName="Jane Doe" email="jane@example.com" />,
    )
    const img = container.querySelector('img')
    expect(img).not.toBeNull()
    fireEvent.error(img as HTMLImageElement)
    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByText('JD')).toBeInTheDocument()
  })

  it('renders a bot glyph (no initials) for automation actors', () => {
    const { container } = render(
      <UserIdentity actor="github-actions[bot]" email="ci@example.com" />,
    )
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('svg')).not.toBeNull()
  })

  it('honors an explicit kind="bot" override', () => {
    const { container } = render(
      <UserIdentity displayName="Deployer" kind="bot" />,
    )
    expect(container.querySelector('svg')).not.toBeNull()
    expect(screen.queryByText('D')).toBeNull()
  })

  it('prefers an explicit image over Gravatar', () => {
    const { container } = render(
      <UserIdentity displayName="Acme Person" image="https://cdn/x.png" />,
    )
    expect(container.querySelector('img')?.getAttribute('src')).toBe(
      'https://cdn/x.png',
    )
  })
})

describe('UserIdentity secondary line', () => {
  it('shows the email as a secondary line at medium size', () => {
    render(
      <UserIdentity
        displayName="Jane Doe"
        email="jane@example.com"
        size="medium"
      />,
    )
    expect(screen.getByText('jane@example.com')).toBeInTheDocument()
  })

  it('hides the secondary line at small/floating size', () => {
    render(
      <UserIdentity
        displayName="Jane Doe"
        email="jane@example.com"
        size="small"
      />,
    )
    expect(screen.queryByText('jane@example.com')).toBeNull()
  })

  it('uses an explicit secondary override when given', () => {
    render(
      <UserIdentity
        displayName="Jane Doe"
        email="jane@example.com"
        secondary="Service owner"
        size="large"
      />,
    )
    expect(screen.getByText('Service owner')).toBeInTheDocument()
    expect(screen.queryByText('jane@example.com')).toBeNull()
  })
})

describe('UserIdentity profile linking', () => {
  it('links to the user profile when an email is known', () => {
    render(<UserIdentity displayName="Jane Doe" email="jane@example.com" />)
    expect(screen.getByRole('link')).toHaveAttribute(
      'href',
      '/users/jane%40example.com',
    )
  })

  it('does not link when linkToProfile is false', () => {
    render(
      <UserIdentity
        displayName="Jane Doe"
        email="jane@example.com"
        linkToProfile={false}
      />,
    )
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('does not link bot actors', () => {
    render(<UserIdentity actor="ci-bot" email="ci@example.com" kind="bot" />)
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('omits the name in hideName mode', () => {
    render(
      <UserIdentity displayName="Jane Doe" email="jane@example.com" hideName />,
    )
    expect(screen.queryByText('Jane Doe')).toBeNull()
  })
})
