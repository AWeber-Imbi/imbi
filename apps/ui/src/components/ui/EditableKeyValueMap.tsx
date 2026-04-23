// Inline-edit key/value card: keys are picked from a pre-known set (Select),
// values commit on blur with a SavedIndicator, and deletes pass through a
// ConfirmDialog. Use on detail pages where each row is independently saved
// against the server (see EditLinksCard, EditIdentifiersCard).
//
// For form-embedded free-form key/value editing where the whole form is
// submitted at once, use KeyValueEditor (./key-value-editor) instead.
import type { ReactNode } from 'react'
import { Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Input } from '@/components/ui/input'
import { SavedIndicator } from '@/components/ui/saved-indicator'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { UseEditableKeyValueMapResult } from '@/hooks/useEditableKeyValueMap'

export interface EditableKeyValueMapProps {
  state: UseEditableKeyValueMapResult<string>
  title: string
  /** Keys shown as existing, editable rows, already in display order. */
  visibleKeys: string[]
  /** Keys available to pick from the "add new" Select, already in order. */
  unassignedKeys: string[]
  /** Left-column label for an existing row (icon + name, plain text, …). */
  renderKeyLabel: (key: string) => ReactNode
  /** Trigger contents when a key has been picked in the "add new" row. */
  renderSelectTrigger: (newKey: string) => ReactNode
  /** Option contents inside each <SelectItem>. */
  renderSelectItem: (key: string) => ReactNode
  /** Placeholder for the value input on an existing row. */
  getValuePlaceholder: (key: string) => string
  /** Placeholder for the new-row value input; receives the picked key or null. */
  getNewValuePlaceholder: (newKey: string | null) => string
  /** Placeholder for the add-row Select when no key is picked. */
  newKeyPlaceholder: string
  /** aria-label for the delete button on an existing row. */
  getRemoveAriaLabel: (key: string) => string
  /** Confirm dialog title; `null` is supplied when pendingDelete is null. */
  getDeleteDialogTitle: (key: string | null) => string
  deleteDialogDescription: string
  /** Classes applied to every value <Input>. */
  valueInputClassName?: string
  valueInputType?: 'text' | 'url'
  /** Hide the whole card when there are no visible and no unassigned keys. */
  hideWhenEmpty?: boolean
  /**
   * Accessible name for an existing row's value input. Defaults to
   * `getValuePlaceholder(key)` so controls always expose a programmatic label.
   */
  getValueAriaLabel?: (key: string) => string
  /**
   * Accessible name for the add-row key select. Defaults to `newKeyPlaceholder`.
   */
  newKeySelectAriaLabel?: string
  /**
   * Accessible name for the add-row value input. Defaults to
   * `getNewValuePlaceholder(newKey)`.
   */
  newValueAriaLabel?: string
}

export function EditableKeyValueMap({
  state,
  title,
  visibleKeys,
  unassignedKeys,
  renderKeyLabel,
  renderSelectTrigger,
  renderSelectItem,
  getValuePlaceholder,
  getNewValuePlaceholder,
  newKeyPlaceholder,
  getRemoveAriaLabel,
  getDeleteDialogTitle,
  deleteDialogDescription,
  valueInputClassName,
  valueInputType = 'text',
  hideWhenEmpty = false,
  getValueAriaLabel,
  newKeySelectAriaLabel,
  newValueAriaLabel,
}: EditableKeyValueMapProps) {
  const {
    drafts,
    setDraft,
    handleBlur,
    requestDelete,
    cancelDelete,
    confirmDelete,
    pendingDelete,
    newKey,
    newValue,
    setNewKey,
    setNewValue,
    handleNewBlur,
    selectKey,
    saved,
    newValueRef,
  } = state

  if (hideWhenEmpty && visibleKeys.length === 0 && unassignedKeys.length === 0)
    return null

  return (
    <Card className="p-6">
      <h3 className="mb-4 text-primary">{title}</h3>

      <div className="space-y-3">
        {visibleKeys.map((key) => (
          <div key={key} className="flex items-center gap-3">
            {renderKeyLabel(key)}
            <div className="relative flex-1">
              <Input
                value={drafts[key] ?? ''}
                onChange={(e) => setDraft(key, e.target.value)}
                onBlur={() => handleBlur(key)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    e.currentTarget.blur()
                  }
                }}
                aria-label={
                  getValueAriaLabel?.(key) ?? getValuePlaceholder(key)
                }
                placeholder={getValuePlaceholder(key)}
                type={valueInputType}
                className={`pr-8 ${valueInputClassName ?? ''}`.trim()}
              />
              <SavedIndicator show={!!saved[key]} />
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={getRemoveAriaLabel(key)}
              className="h-8 w-8 flex-shrink-0 text-secondary hover:text-danger"
              onClick={() => requestDelete(key)}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        ))}

        {unassignedKeys.length > 0 && (
          <div className="flex items-center gap-3 pt-2">
            <Select
              key={selectKey}
              value={newKey ?? ''}
              onValueChange={setNewKey}
            >
              <SelectTrigger
                aria-label={newKeySelectAriaLabel ?? newKeyPlaceholder}
                className="w-[15%] flex-shrink-0 text-sm"
              >
                {newKey ? (
                  renderSelectTrigger(newKey)
                ) : (
                  <SelectValue placeholder={newKeyPlaceholder} />
                )}
              </SelectTrigger>
              <SelectContent>
                {unassignedKeys.map((key) => (
                  <SelectItem key={key} value={key}>
                    {renderSelectItem(key)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              ref={newValueRef}
              value={newValue ?? ''}
              onChange={(e) => setNewValue(e.target.value)}
              onBlur={handleNewBlur}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  e.currentTarget.blur()
                }
              }}
              aria-label={newValueAriaLabel ?? getNewValuePlaceholder(newKey)}
              placeholder={getNewValuePlaceholder(newKey)}
              type={valueInputType}
              disabled={!newKey}
              className={`flex-1 ${valueInputClassName ?? ''}`.trim()}
            />
            <div className="h-8 w-8 flex-shrink-0" aria-hidden />
          </div>
        )}
      </div>

      <ConfirmDialog
        open={pendingDelete !== null}
        title={getDeleteDialogTitle(pendingDelete)}
        description={deleteDialogDescription}
        confirmLabel="Remove"
        onConfirm={confirmDelete}
        onCancel={cancelDelete}
      />
    </Card>
  )
}
