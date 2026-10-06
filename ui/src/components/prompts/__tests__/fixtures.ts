import type { Prompt, PromptVersion } from '@/types'

export const prompt = (overrides: Partial<Prompt> = {}): Prompt => ({
  created_at: '2026-10-01T12:00:00Z',
  default_label: 'stable',
  id: 'prm-1',
  kind: 'generative',
  labels: [
    {
      name: 'stable',
      updated_at: '2026-10-01T12:00:00Z',
      updated_by: 'grantr@example.com',
      version: 2,
    },
  ],
  latest_version: 2,
  name: 'Mender core',
  namespace: 'mender',
  ref: 'mender/core',
  slug: 'core',
  type: 'core_system',
  updated_at: '2026-10-01T12:00:00Z',
  ...overrides,
})

export const version = (n: number): PromptVersion => ({
  content_sha256: `${n}`.repeat(64),
  created_at: '2026-10-01T12:00:00Z',
  created_by: 'grantr@example.com',
  eval_summary: null,
  id: `ver-${n}`,
  labels: n === 2 ? ['stable'] : [],
  messages: [],
  model: null,
  model_id: null,
  n,
  params: { max_tokens: 4096, stop_sequences: [], temperature: 1 },
  questions: {},
  ref: `mender/core@${n}`,
  state: '',
  summary: `Change ${n}`,
  system: `You triage v${n}.`,
  tools: [],
  variable_schema: {},
})
