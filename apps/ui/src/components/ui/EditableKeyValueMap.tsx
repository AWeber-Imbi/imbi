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
  deleteDialogDescription: string
  /** Confirm dialog title; `null` is supplied when pendingDelete is null. */
  getDeleteDialogTitle: (key: null | string) => string
  /** Placeholder for the new-row value input; receives the picked key or null. */
  getNewValuePlaceholder: (newKey: null | string) => string
  /** aria-label for the delete button on an existing row. */
  getRemoveAriaLabel: (key: string) => string
  /**
   * Accessible name for an existing row's value input. Defaults to
   * `getValuePlaceholder(key)` so controls always expose a programmatic label.
   */
  getValueAriaLabel?: (key: string) => string
  /** Placeholder for the value input on an existing row. */
  getValuePlaceholder: (key: string) => string
  /** Hide the whole card when there are no visible and no unassigned keys. */
  hideWhenEmpty?: boolean
  /** Placeholder for the add-row Select when no key is picked. */
  newKeyPlaceholder: string
  /**
   * Accessible name for the add-row key select. Defaults to `newKeyPlaceholder`.
   */
  newKeySelectAriaLabel?: string
  /**
   * Accessible name for the add-row value input. Defaults to
   * `getNewValuePlaceholder(newKey)`.
   */
  newValueAriaLabel?: string
  /** Left-column label for an existing row (icon + name, plain text, …). */
  renderKeyLabel: (key: string) => ReactNode
  /** Option contents inside each <SelectItem>. */
  renderSelectItem: (key: string) => ReactNode
  /** Trigger contents when a key has been picked in the "add new" row. */
  renderSelectTrigger: (newKey: string) => ReactNode
  state: UseEditableKeyValueMapResult<string>
  title: string
  /** Keys available to pick from the "add new" Select, already in order. */
  unassignedKeys: string[]
  /** Classes applied to every value <Input>. */
  valueInputClassName?: string
  valueInputType?: 'text' | 'url'
  /** Keys shown as existing, editable rows, already in display order. */
  visibleKeys: string[]
}

export function EditableKeyValueMap({
  deleteDialogDescription,
  getDeleteDialogTitle,
  getNewValuePlaceholder,
  getRemoveAriaLabel,
  getValueAriaLabel,
  getValuePlaceholder,
  hideWhenEmpty = false,
  newKeyPlaceholder,
  newKeySelectAriaLabel,
  newValueAriaLabel,
  renderKeyLabel,
  renderSelectItem,
  renderSelectTrigger,
  state,
  title,
  unassignedKeys,
  valueInputClassName,
  valueInputType = 'text',
  visibleKeys,
}: EditableKeyValueMapProps) {
  const {
    cancelDelete,
    confirmDelete,
    drafts,
    handleBlur,
    handleNewBlur,
    newKey,
    newValue,
    newValueRef,
    pendingDelete,
    requestDelete,
    saved,
    selectKey,
    setDraft,
    setNewKey,
    setNewValue,
  } = state

  if (hideWhenEmpty && visibleKeys.length === 0 && unassignedKeys.length === 0)
    return null

  return (
    <Card className="p-6">
      <h3 className="mb-4 text-primary">{title}</h3>

      <div className="space-y-3">
        {visibleKeys.map((key) => (
          <div className="flex items-center gap-3" key={key}>
            {renderKeyLabel(key)}
            <div className="relative flex-1">
              <Input
                aria-label={
                  getValueAriaLabel?.(key) ?? getValuePlaceholder(key)
                }
                className={`pr-8 ${valueInputClassName ?? ''}`.trim()}
                onBlur={() => handleBlur(key)}
                onChange={(e) => setDraft(key, e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    e.currentTarget.blur()
                  }
                }}
                placeholder={getValuePlaceholder(key)}
                type={valueInputType}
                value={drafts[key] ?? ''}
              />
              <SavedIndicator show={!!saved[key]} />
            </div>
            <Button
              aria-label={getRemoveAriaLabel(key)}
              className="h-8 w-8 flex-shrink-0 text-secondary hover:text-danger"
              onClick={() => requestDelete(key)}
              size="icon"
              type="button"
              variant="ghost"
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        ))}

        {unassignedKeys.length > 0 && (
          <div className="flex items-center gap-3 pt-2">
            <Select
              key={selectKey}
              onValueChange={setNewKey}
              value={newKey ?? ''}
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
              aria-label={newValueAriaLabel ?? getNewValuePlaceholder(newKey)}
              className={`flex-1 ${valueInputClassName ?? ''}`.trim()}
              disabled={!newKey}
              onBlur={handleNewBlur}
              onChange={(e) => setNewValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  e.currentTarget.blur()
                }
              }}
              placeholder={getNewValuePlaceholder(newKey)}
              ref={newValueRef}
              type={valueInputType}
              value={newValue ?? ''}
            />
            <div aria-hidden className="h-8 w-8 flex-shrink-0" />
          </div>
        )}
      </div>

      <ConfirmDialog
        confirmLabel="Remove"
        description={deleteDialogDescription}
        onCancel={cancelDelete}
        onConfirm={confirmDelete}
        open={pendingDelete !== null}
        title={getDeleteDialogTitle(pendingDelete)}
      />
    </Card>
  )
}
