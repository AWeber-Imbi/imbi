import { type MouseEvent, type ReactNode, useEffect, useState } from 'react'

import { Link, useNavigate } from 'react-router-dom'

import { Trash2 } from 'lucide-react'

import { cn } from '@/lib/utils'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from './alert-dialog'
import { Button } from './button'
import { Card, CardContent } from './card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from './dialog'
import { Sk } from './skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from './table'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from './tooltip'

export interface AdminTableColumn<T> {
  cellAlign?: 'center' | 'left' | 'right'
  header: string
  headerAlign?: 'center' | 'left' | 'right'
  // When the cell renders its own interactive content (links, buttons,
  // toggles), set this so the cell stacks above the row link overlay and
  // stays clickable.
  interactive?: boolean
  key: string
  render: (row: T) => ReactNode
}

export interface BlockedReason {
  count: number
  href?: string // optional link to filtered view
  label: string // e.g. "project", "team", "member"
}

export interface CanDeleteResult {
  allowed: boolean
  blockedBy?: BlockedReason[] // structured blocking conditions
  reason?: string // free-form fallback (system roles, etc.)
}

interface AdminTableProps<T> {
  actions?: (row: T) => ReactNode
  canDelete?: (row: T) => CanDeleteResult
  columns: AdminTableColumn<T>[]
  emptyMessage?: string
  getDeleteLabel?: (row: T) => string
  // Returns the destination for a row. When provided, the row renders a real
  // anchor so cmd/ctrl/middle-click and the browser context menu work
  // natively. Return undefined to make a row non-navigable.
  getRowHref?: (row: T) => string | undefined
  getRowKey: (row: T) => string
  getRowLabel?: (row: T) => string
  isDeleting?: boolean
  isRowClickable?: (row: T) => boolean
  /** Render footprint-matched skeleton rows instead of data while loading. */
  loading?: boolean
  onDelete?: (row: T) => void
  rows: T[]
  /** Number of skeleton rows to show while loading. */
  skeletonRows?: number
}

const HEADER_ALIGN: Record<string, string> = {
  center: 'text-center',
  left: 'text-left',
  right: 'text-right',
}

const CELL_ALIGN: Record<string, string> = {
  center: 'text-center',
  left: 'text-left',
  right: 'text-right',
}

const CELL_JUSTIFY: Record<string, string> = {
  center: 'justify-center',
  left: 'justify-start',
  right: 'justify-end',
}

// Skeleton line width per column alignment — left columns hold the primary
// label (wide), centered/right columns hold codes, counts, dates (narrow).
const SKELETON_WIDTH: Record<string, number | string> = {
  center: 64,
  left: '60%',
  right: 40,
}

interface AdminRowActionsProps<T> {
  actions?: (row: T) => ReactNode
  deleteCheck: CanDeleteResult
  isDeleting: boolean
  label: string
  onDelete?: (row: T) => void
  onDeleteClick: (
    row: T,
    e: MouseEvent<HTMLButtonElement>,
    deleteCheck: CanDeleteResult,
  ) => void
  row: T
}

interface AdminTableRowProps<T> {
  actions?: (row: T) => ReactNode
  canDelete?: (row: T) => CanDeleteResult
  columns: AdminTableColumn<T>[]
  getDeleteLabel?: (row: T) => string
  getRowHref?: (row: T) => string | undefined
  getRowLabel?: (row: T) => string
  isDeleting: boolean
  isRowClickable?: (row: T) => boolean
  onDelete?: (row: T) => void
  onDeleteClick: (
    row: T,
    e: MouseEvent<HTMLButtonElement>,
    deleteCheck: CanDeleteResult,
  ) => void
  row: T
  showActions: boolean
}

export function AdminTable<T>({
  actions,
  canDelete,
  columns,
  emptyMessage = 'No items found.',
  getDeleteLabel,
  getRowHref,
  getRowKey,
  getRowLabel,
  isDeleting = false,
  isRowClickable,
  loading = false,
  onDelete,
  rows,
  skeletonRows = 5,
}: AdminTableProps<T>) {
  const navigate = useNavigate()
  const [deleteTarget, setDeleteTarget] = useState<null | T>(null)
  const [blockedTarget, setBlockedTarget] = useState<null | {
    result: CanDeleteResult
    row: T
  }>(null)
  const [wasDeleting, setWasDeleting] = useState(false)

  useEffect(() => {
    if (isDeleting) {
      setWasDeleting(true)
    } else if (wasDeleting) {
      setWasDeleting(false)
      setDeleteTarget(null)
    }
  }, [isDeleting, wasDeleting])

  const handleDeleteClick = (
    row: T,
    e: MouseEvent<HTMLButtonElement>,
    deleteCheck: CanDeleteResult,
  ) => {
    e.stopPropagation()
    if (!deleteCheck.allowed) {
      setBlockedTarget({ result: deleteCheck, row })
    } else {
      setDeleteTarget(row)
    }
  }

  const handleDeleteConfirm = () => {
    if (deleteTarget && onDelete) {
      onDelete(deleteTarget)
      // Don't close here — caller signals success by completing the mutation
    }
  }

  const showActions = !!onDelete || !!actions

  return (
    <>
      <Dialog
        onOpenChange={(open) => {
          if (!open) setBlockedTarget(null)
        }}
        open={blockedTarget !== null}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Restricted</DialogTitle>
            <DialogDescription>
              This item cannot be deleted at this time.
            </DialogDescription>
          </DialogHeader>
          <div className="p-6">
            {blockedTarget &&
              (() => {
                const name = getDeleteLabel
                  ? getDeleteLabel(blockedTarget.row)
                  : ''
                const { blockedBy, reason } = blockedTarget.result
                if (blockedBy && blockedBy.length > 0) {
                  const parts = blockedBy.map((b, i) => (
                    <span key={i}>
                      {b.href ? (
                        <Button
                          className="text-primary h-auto p-0 font-medium underline underline-offset-2 hover:opacity-80"
                          onClick={() => {
                            setBlockedTarget(null)
                            navigate(b.href!)
                          }}
                          variant="link"
                        >
                          {b.count.toLocaleString()} {b.label}
                          {b.count !== 1 ? 's' : ''}
                        </Button>
                      ) : (
                        <span className="font-medium">
                          {b.count.toLocaleString()} {b.label}
                          {b.count !== 1 ? 's' : ''}
                        </span>
                      )}
                    </span>
                  ))
                  const joined = parts.reduce<ReactNode[]>((acc, el, i) => {
                    if (i === 0) return [el]
                    if (i === parts.length - 1) return [...acc, ' and ', el]
                    return [...acc, ', ', el]
                  }, [])
                  return (
                    <p className="text-sm">
                      <span className="font-semibold">{name}</span> cannot be
                      deleted because it is referenced by {joined}. Remove or
                      reassign
                      {blockedBy.length === 1
                        ? blockedBy[0].count === 1
                          ? ` that ${blockedBy[0].label}`
                          : ` those ${blockedBy[0].label}s`
                        : 'them'}{' '}
                      before deleting this item.
                    </p>
                  )
                }
                return (
                  <p className="text-sm">
                    <span className="font-semibold">{name}</span> cannot be
                    deleted
                    {reason
                      ? `: ${reason.toLowerCase().replace(/^cannot delete the only /, 'because it is the only ')}.`
                      : '.'}
                  </p>
                )
              })()}
          </div>
          <DialogFooter>
            <Button onClick={() => setBlockedTarget(null)}>OK</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog
        onOpenChange={(open) => {
          if (!open && !isDeleting) setDeleteTarget(null)
        }}
        open={deleteTarget !== null}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Delete &quot;
              {deleteTarget && getDeleteLabel
                ? getDeleteLabel(deleteTarget)
                : ''}
              &quot;?
            </AlertDialogTitle>
            <AlertDialogDescription>
              This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={handleDeleteConfirm}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                {columns.map((col) => (
                  <TableHead
                    className={HEADER_ALIGN[col.headerAlign ?? 'left']}
                    key={col.key}
                  >
                    {col.header}
                  </TableHead>
                ))}
                {showActions && (
                  <TableHead className="text-right">Actions</TableHead>
                )}
              </TableRow>
            </TableHeader>
            <TableBody aria-busy={loading || undefined}>
              {loading ? (
                Array.from({ length: skeletonRows }).map((_, i) => (
                  <TableRow key={`skeleton-${i}`}>
                    {columns.map((col) => (
                      <TableCell
                        className={CELL_ALIGN[col.cellAlign ?? 'left']}
                        key={col.key}
                      >
                        <div
                          className={cn(
                            'flex',
                            CELL_JUSTIFY[col.cellAlign ?? 'left'],
                          )}
                        >
                          <Sk
                            line
                            w={SKELETON_WIDTH[col.cellAlign ?? 'left']}
                          />
                        </div>
                      </TableCell>
                    ))}
                    {showActions && (
                      <TableCell className="text-right">
                        <div className="flex justify-end">
                          <Sk h={20} r={4} w={20} />
                        </div>
                      </TableCell>
                    )}
                  </TableRow>
                ))
              ) : rows.length === 0 ? (
                <TableRow>
                  <TableCell
                    className="text-muted-foreground py-12 text-center"
                    colSpan={columns.length + (showActions ? 1 : 0)}
                  >
                    {emptyMessage}
                  </TableCell>
                </TableRow>
              ) : (
                rows.map((row) => (
                  <AdminTableRow
                    actions={actions}
                    canDelete={canDelete}
                    columns={columns}
                    getDeleteLabel={getDeleteLabel}
                    getRowHref={getRowHref}
                    getRowLabel={getRowLabel}
                    isDeleting={isDeleting}
                    isRowClickable={isRowClickable}
                    key={getRowKey(row)}
                    onDelete={onDelete}
                    onDeleteClick={handleDeleteClick}
                    row={row}
                    showActions={showActions}
                  />
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </>
  )
}

function AdminRowActions<T>({
  actions,
  deleteCheck,
  isDeleting,
  label,
  onDelete,
  onDeleteClick,
  row,
}: AdminRowActionsProps<T>) {
  return (
    <TableCell
      className="relative z-10 text-right"
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
    >
      <div className="flex items-center justify-end gap-2">
        {actions && actions(row)}
        {onDelete && (
          <TooltipProvider delayDuration={200}>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="inline-flex">
                  <Button
                    aria-label={`Delete ${label}`}
                    className={cn(
                      'text-destructive hover:bg-destructive/10 hover:text-destructive',
                      isDeleting && 'pointer-events-none opacity-30',
                      !deleteCheck.allowed && 'opacity-30',
                    )}
                    disabled={isDeleting}
                    onClick={(e) => onDeleteClick(row, e, deleteCheck)}
                    size="sm"
                    variant="ghost"
                  >
                    <Trash2 className="size-4" />
                  </Button>
                </span>
              </TooltipTrigger>
              <TooltipContent>
                <p>{deleteCheck.reason ?? 'Delete'}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        )}
      </div>
    </TableCell>
  )
}

function AdminTableRow<T>({
  actions,
  canDelete,
  columns,
  getDeleteLabel,
  getRowHref,
  getRowLabel,
  isDeleting,
  isRowClickable,
  onDelete,
  onDeleteClick,
  row,
  showActions,
}: AdminTableRowProps<T>) {
  const label = resolveLabel(row, getRowLabel, getDeleteLabel)
  const deleteCheck = canDelete ? canDelete(row) : { allowed: true }
  const clickable = isRowClickable ? isRowClickable(row) : true
  const href = getRowHref && clickable ? getRowHref(row) : undefined

  return (
    <TableRow className={cn(href && 'relative cursor-pointer')}>
      {columns.map((col, colIndex) => (
        <TableCell
          className={cn(
            CELL_ALIGN[col.cellAlign ?? 'left'],
            col.interactive && 'relative z-10',
          )}
          key={col.key}
        >
          {href && colIndex === 0 && (
            <Link
              aria-label={label ? `Open ${label}` : 'Open item'}
              className="focus-visible:ring-ring absolute inset-0 rounded-sm focus-visible:ring-2 focus-visible:outline-none"
              to={href}
            />
          )}
          {col.render(row)}
        </TableCell>
      ))}
      {showActions && (
        <AdminRowActions
          actions={actions}
          deleteCheck={deleteCheck}
          isDeleting={isDeleting}
          label={label}
          onDelete={onDelete}
          onDeleteClick={onDeleteClick}
          row={row}
        />
      )}
    </TableRow>
  )
}

function resolveLabel<T>(
  row: T,
  getRowLabel?: (row: T) => string,
  getDeleteLabel?: (row: T) => string,
): string {
  if (getRowLabel) return getRowLabel(row)
  if (getDeleteLabel) return getDeleteLabel(row)
  return ''
}
