import { useState, useEffect, type MouseEvent, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { Trash2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from './button'
import { Card, CardContent } from './card'
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from './dialog'
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
  key: string
  header: string
  headerAlign?: 'left' | 'center' | 'right'
  cellAlign?: 'left' | 'center' | 'right'
  render: (row: T) => ReactNode
}

export interface BlockedReason {
  count: number
  label: string // e.g. "project", "team", "member"
  href?: string // optional link to filtered view
}

export interface CanDeleteResult {
  allowed: boolean
  reason?: string // free-form fallback (system roles, etc.)
  blockedBy?: BlockedReason[] // structured blocking conditions
}

interface AdminTableProps<T> {
  columns: AdminTableColumn<T>[]
  rows: T[]
  getRowKey: (row: T) => string
  getRowLabel?: (row: T) => string
  getDeleteLabel: (row: T) => string
  onRowClick?: (row: T) => void
  isRowClickable?: (row: T) => boolean
  onDelete: (row: T) => void
  canDelete?: (row: T) => CanDeleteResult
  isDeleting?: boolean
  actions?: (row: T) => ReactNode
  emptyMessage?: string
}

const HEADER_ALIGN: Record<string, string> = {
  left: 'text-left',
  center: 'text-center',
  right: 'text-right',
}

const CELL_ALIGN: Record<string, string> = {
  left: 'text-left',
  center: 'text-center',
  right: 'text-right',
}

export function AdminTable<T>({
  columns,
  rows,
  getRowKey,
  getRowLabel,
  getDeleteLabel,
  onRowClick,
  isRowClickable,
  onDelete,
  canDelete,
  isDeleting = false,
  actions,
  emptyMessage = 'No items found.',
}: AdminTableProps<T>) {
  const navigate = useNavigate()
  const [deleteTarget, setDeleteTarget] = useState<T | null>(null)
  const [blockedTarget, setBlockedTarget] = useState<{
    row: T
    result: CanDeleteResult
  } | null>(null)
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
      setBlockedTarget({ row, result: deleteCheck })
    } else {
      setDeleteTarget(row)
    }
  }

  const handleDeleteConfirm = () => {
    if (deleteTarget) {
      onDelete(deleteTarget)
      // Don't close here — caller signals success by completing the mutation
    }
  }

  return (
    <>
      <Dialog
        open={blockedTarget !== null}
        onOpenChange={(open) => {
          if (!open) setBlockedTarget(null)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Restricted</DialogTitle>
            <DialogDescription>
              This item cannot be deleted at this time.
            </DialogDescription>
          </DialogHeader>
          {blockedTarget &&
            (() => {
              const name = getDeleteLabel(blockedTarget.row)
              const { blockedBy, reason } = blockedTarget.result
              if (blockedBy && blockedBy.length > 0) {
                const parts = blockedBy.map((b, i) => (
                  <span key={i}>
                    {b.href ? (
                      <button
                        className="font-medium text-primary underline underline-offset-2 hover:opacity-80"
                        onClick={() => {
                          setBlockedTarget(null)
                          navigate(b.href!)
                        }}
                      >
                        {b.count} {b.label}
                        {b.count !== 1 ? 's' : ''}
                      </button>
                    ) : (
                      <span className="font-medium">
                        {b.count} {b.label}
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
          <DialogFooter>
            <Button onClick={() => setBlockedTarget(null)}>OK</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open && !isDeleting) setDeleteTarget(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Delete &quot;{deleteTarget ? getDeleteLabel(deleteTarget) : ''}
              &quot;?
            </AlertDialogTitle>
            <AlertDialogDescription>
              This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDeleteConfirm}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
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
                    key={col.key}
                    className={HEADER_ALIGN[col.headerAlign ?? 'left']}
                  >
                    {col.header}
                  </TableHead>
                ))}
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={columns.length + 1}
                    className="py-12 text-center text-muted-foreground"
                  >
                    {emptyMessage}
                  </TableCell>
                </TableRow>
              ) : (
                rows.map((row) => {
                  const key = getRowKey(row)
                  const label = getRowLabel
                    ? getRowLabel(row)
                    : getDeleteLabel(row)
                  const deleteCheck = canDelete
                    ? canDelete(row)
                    : { allowed: true }
                  const canDeleteRow = deleteCheck.allowed
                  const deleteReason = deleteCheck.reason
                  const rowClickable =
                    onRowClick && (isRowClickable ? isRowClickable(row) : true)

                  return (
                    <TableRow
                      key={key}
                      onClick={rowClickable ? () => onRowClick(row) : undefined}
                      onKeyDown={
                        rowClickable
                          ? (e) => {
                              if (e.currentTarget !== e.target) return
                              if (e.key === 'Enter' || e.key === ' ') {
                                e.preventDefault()
                                onRowClick(row)
                              }
                            }
                          : undefined
                      }
                      tabIndex={rowClickable ? 0 : undefined}
                      aria-label={rowClickable ? `Edit ${label}` : undefined}
                      className={cn(rowClickable && 'cursor-pointer')}
                    >
                      {columns.map((col) => (
                        <TableCell
                          key={col.key}
                          className={CELL_ALIGN[col.cellAlign ?? 'left']}
                        >
                          {col.render(row)}
                        </TableCell>
                      ))}
                      <TableCell
                        className="text-right"
                        onClick={(e) => e.stopPropagation()}
                        onKeyDown={(e) => e.stopPropagation()}
                      >
                        <div className="flex items-center justify-end gap-2">
                          {actions && actions(row)}
                          <TooltipProvider delayDuration={200}>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <span className="inline-flex">
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    aria-label={`Delete ${label}`}
                                    onClick={(e) =>
                                      handleDeleteClick(row, e, deleteCheck)
                                    }
                                    disabled={isDeleting}
                                    className={cn(
                                      'text-destructive hover:bg-destructive/10 hover:text-destructive',
                                      isDeleting &&
                                        'pointer-events-none opacity-30',
                                      !canDeleteRow && 'opacity-30',
                                    )}
                                  >
                                    <Trash2 className="h-4 w-4" />
                                  </Button>
                                </span>
                              </TooltipTrigger>
                              {deleteReason && (
                                <TooltipContent>
                                  <p>{deleteReason}</p>
                                </TooltipContent>
                              )}
                            </Tooltip>
                          </TooltipProvider>
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </>
  )
}
