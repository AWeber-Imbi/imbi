import { describe, expect, it } from 'vitest'

import { render, screen } from '@/test/utils'
import type { DocumentAttachment } from '@/types'

import { DocumentAttachmentBadge } from './DocumentAttachmentBadge'

describe('DocumentAttachmentBadge', () => {
  it('links a project attachment to its project page', () => {
    const attachment: DocumentAttachment = {
      id: '42',
      kind: 'project',
      name: 'imbi-api',
    }
    render(<DocumentAttachmentBadge attachment={attachment} />)

    expect(screen.getByText('Project')).toBeInTheDocument()
    const link = screen.getByRole('link', { name: 'imbi-api' })
    expect(link).toHaveAttribute('href', '/projects/42')
  })

  it('labels a project-type attachment without a link', () => {
    const attachment: DocumentAttachment = {
      id: 'api',
      kind: 'project_type',
      name: 'API',
    }
    render(<DocumentAttachmentBadge attachment={attachment} />)

    expect(screen.getByText('Project type')).toBeInTheDocument()
    expect(screen.getByText('API')).toBeInTheDocument()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('labels a user attachment as Personal, falling back to id', () => {
    const attachment: DocumentAttachment = {
      id: 'gavinr@aweber.com',
      kind: 'user',
      name: '',
    }
    render(<DocumentAttachmentBadge attachment={attachment} />)

    expect(screen.getByText('Personal')).toBeInTheDocument()
    expect(screen.getByText('gavinr@aweber.com')).toBeInTheDocument()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })
})
