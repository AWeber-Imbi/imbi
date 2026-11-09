/** The AWS STS claim that holds the request tags of the identity JWT. */
const TAGS = 'claims["https://sts.amazonaws.com/"].request_tags'

type WifSubjectTag = 'imbi_agent' | 'imbi_ai_provider'

/**
 * The CEL condition of an Anthropic federation rule for one agent or AI
 * Provider. It matches `sub` exactly, because `subject_prefix` is a
 * prefix match (docs/admin/workload-identity.md, step 3).
 */
export function anthropicCondition(
  roleArn: string,
  orgId: string,
  tag: WifSubjectTag,
  subjectId: string,
): string {
  return [
    `claims.sub == ${JSON.stringify(roleArn)}`,
    `${TAGS}.imbi_org == ${JSON.stringify(orgId)}`,
    `${TAGS}.${tag} == ${JSON.stringify(subjectId)}`,
  ].join(' &&\n')
}

/**
 * The claims of an OpenAI mapping for one AI Provider. The identity
 * provider stores each CEL attribute with the `openai.` prefix
 * (docs/admin/workload-identity.md, step 4). The values are raw, not
 * quoted: the OpenAI console takes each claim as `key = value`, and an
 * ARN or an id has no whitespace.
 */
export function openaiMapping(
  roleArn: string,
  orgId: string,
  providerId: string,
): string {
  return [
    `sub = ${roleArn}`,
    `openai.imbi_org = ${orgId}`,
    `openai.imbi_ai_provider = ${providerId}`,
  ].join('\n')
}

/**
 * The AI Provider values, by driver. A driver without an entry here has
 * no value builder, so the setup table does not list it.
 */
export const PROVIDER_VALUES: Record<
  string,
  {
    kind: string
    value: (roleArn: string, orgId: string, providerId: string) => string
  }
> = {
  anthropic: {
    kind: 'AI Provider (Anthropic rule)',
    value: (roleArn, orgId, providerId) =>
      anthropicCondition(roleArn, orgId, 'imbi_ai_provider', providerId),
  },
  openai: { kind: 'AI Provider (OpenAI mapping)', value: openaiMapping },
}
