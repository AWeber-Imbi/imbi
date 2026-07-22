import { UserIdentity } from '@/components/ui/user-identity'

/**
 * Performer avatar for the dense ops-log grid (column 7) — avatar-only with a
 * name tooltip. Shared by the release card and the stream row so both rows
 * attribute their performer identically.
 */
export function OpsLogPerformer({
  displayName,
  performer,
}: {
  displayName: null | string
  performer: null | string
}) {
  return (
    <span
      className="self-center justify-self-end"
      style={{ gridColumn: 7, gridRow: '1 / -1' }}
      title={displayName ?? undefined}
    >
      <UserIdentity
        displayName={displayName}
        email={performer}
        hideName
        linkToProfile={false}
        size="small"
      />
    </span>
  )
}
