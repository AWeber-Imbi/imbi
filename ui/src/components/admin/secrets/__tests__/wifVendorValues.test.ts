import { describe, expect, it } from 'vitest'

import { anthropicCondition, openaiMapping } from '../wifVendorValues'

const ARN = 'arn:aws:iam::123456789012:role/imbi-identity'

describe('wifVendorValues', () => {
  it('builds the Anthropic rule condition', () => {
    expect(anthropicCondition(ARN, 'org-1', 'imbi_agent', 'agent-1')).toBe(
      `claims.sub == "${ARN}" &&\n` +
        'claims["https://sts.amazonaws.com/"].request_tags.imbi_org == "org-1" &&\n' +
        'claims["https://sts.amazonaws.com/"].request_tags.imbi_agent == "agent-1"',
    )
  })

  it('builds the OpenAI mapping claims', () => {
    expect(openaiMapping(ARN, 'org-1', 'prov-1')).toBe(
      `sub = ${ARN}\nopenai.imbi_org = org-1\nopenai.imbi_ai_provider = prov-1`,
    )
  })
})
