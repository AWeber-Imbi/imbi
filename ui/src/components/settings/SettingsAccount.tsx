import { useMutation, useQueryClient } from '@tanstack/react-query'

import { updateCurrentUserDisplayName } from '@/api/endpoints'
import { Card } from '@/components/ui/card'
import { InlineText } from '@/components/ui/inline-edit/InlineText'
import { Label } from '@/components/ui/label'
import { useAuth } from '@/hooks/useAuth'
import { extractApiErrorDetail } from '@/lib/apiError'

export function SettingsAccount() {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: updateCurrentUserDisplayName,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['currentUser'] }),
  })

  const commitDisplayName = async (next: null | string) => {
    const trimmed = next?.trim() ?? ''
    if (!trimmed) throw new Error('Display name is required')
    try {
      await mutation.mutateAsync(trimmed)
    } catch (e) {
      throw new Error(extractApiErrorDetail(e))
    }
  }

  return (
    <Card className="p-8" style={{ borderWidth: '0.5px' }}>
      <h2 className="text-primary mb-6 text-[18px] font-medium">
        Account settings
      </h2>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <div>
          <Label>Display name</Label>
          <div className="text-primary mt-2 text-[13.5px]">
            <InlineText
              onCommit={commitDisplayName}
              pending={mutation.isPending}
              placeholder="Add display name"
              value={user?.display_name ?? ''}
            />
          </div>
        </div>
        <div>
          <Label>Email address</Label>
          <p className="text-tertiary mt-2 text-[13.5px]">
            {user?.email || '—'}
          </p>
        </div>
      </div>
    </Card>
  )
}
