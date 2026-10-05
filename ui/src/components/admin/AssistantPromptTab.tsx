import { useState } from 'react'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { FileCode2, Info } from 'lucide-react'
import { toast } from 'sonner'

import { createPrompt } from '@/api/endpoints'
import { NewPromptDialog } from '@/components/prompts/NewPromptDialog'
import { PromptEditor } from '@/components/prompts/PromptEditor'
import { Button } from '@/components/ui/button'
import { useHasPermission } from '@/hooks/useHasPermission'
import { extractApiErrorDetail } from '@/lib/apiError'
import { queryKeys } from '@/lib/queryKeys'
import type { PromptCreate } from '@/types'

const NAMESPACE = 'imbi-assistant'
const SLUG = 'system'

/** The assistant's system prompt, edited in place through the CMS. */
export function AssistantPromptTab() {
  const queryClient = useQueryClient()
  const canCreate = useHasPermission('prompt:create')
  const [creating, setCreating] = useState(false)

  const create = useMutation({
    mutationFn: (body: PromptCreate) => createPrompt(body),
    onError: (err) => toast.error(extractApiErrorDetail(err)),
    onSuccess: async () => {
      setCreating(false)
      await queryClient.invalidateQueries({
        queryKey: queryKeys.prompts(),
      })
    },
  })

  return (
    <div className="space-y-4">
      <div
        className="border-tertiary bg-secondary text-secondary flex items-center gap-2 rounded-md border px-3 py-2 text-sm"
        style={{ borderWidth: '0.5px' }}
      >
        <Info className="size-3.5 flex-none" />
        imbi-assistant uses the version the stable label points at. Until this
        prompt exists, it uses its built-in prompt; run imbi-api setup-prompts
        to create it.
      </div>
      <PromptEditor
        emptyState={
          <div className="grid place-items-center py-16">
            <div className="max-w-sm text-center">
              <div className="bg-secondary text-tertiary mx-auto mb-3 grid size-11 place-items-center rounded-lg">
                <FileCode2 className="size-5" />
              </div>
              <div className="text-primary text-[15px] font-medium">
                The assistant prompt is not in the CMS yet
              </div>
              <p className="text-secondary mt-1 text-sm">
                Create {NAMESPACE}/{SLUG} to version the assistant&apos;s system
                prompt, model, and parameters.
              </p>
              {canCreate && (
                <Button
                  className="mt-4"
                  onClick={() => setCreating(true)}
                  size="sm"
                >
                  Create assistant prompt
                </Button>
              )}
            </div>
          </div>
        }
        namespace={NAMESPACE}
        slug={SLUG}
      />
      {creating && (
        <NewPromptDialog
          defaults={{
            name: 'Assistant system prompt',
            namespace: NAMESPACE,
            slug: SLUG,
            type: 'core_system',
          }}
          locked
          namespaces={[NAMESPACE]}
          onClose={() => setCreating(false)}
          onSubmit={(body) => create.mutate(body)}
          open
          pending={create.isPending}
        />
      )}
    </div>
  )
}
