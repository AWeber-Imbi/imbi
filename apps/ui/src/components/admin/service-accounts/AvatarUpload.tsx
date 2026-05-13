import { useRef } from 'react'

import { Camera, Loader2, X } from 'lucide-react'

interface AvatarUploadProps {
  avatarUrl?: null | string
  displayName: string
  isRemoving?: boolean
  isUploading?: boolean
  onRemove: () => void
  onUpload: (file: File) => void
}

export function AvatarUpload({
  avatarUrl,
  displayName,
  isRemoving = false,
  isUploading = false,
  onRemove,
  onUpload,
}: AvatarUploadProps) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const isLoading = isUploading || isRemoving

  const initials = displayName
    .split(/\s+/)
    .map((w) => w[0])
    .join('')
    .toUpperCase()
    .slice(0, 2)

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) onUpload(file)
    // Reset so the same file can be re-selected after a removal
    e.target.value = ''
  }

  return (
    <div className="relative shrink-0">
      {/* Hidden file input */}
      <input
        accept="image/*"
        className="hidden"
        onChange={handleFileChange}
        ref={fileInputRef}
        type="file"
      />

      {/* Avatar circle */}
      <button
        className="group border-tertiary bg-secondary relative size-14 overflow-hidden rounded-full border transition-opacity disabled:cursor-not-allowed disabled:opacity-60"
        disabled={isLoading}
        onClick={() => fileInputRef.current?.click()}
        title="Upload avatar"
        type="button"
      >
        {avatarUrl ? (
          <img
            alt={displayName}
            className="size-full object-cover"
            src={avatarUrl}
          />
        ) : (
          <span className="text-secondary flex size-full items-center justify-center font-mono text-sm font-medium">
            {initials || '?'}
          </span>
        )}

        {/* Hover overlay */}
        {!isLoading && (
          <span className="absolute inset-0 flex items-center justify-center rounded-full bg-black/40 opacity-0 transition-opacity group-hover:opacity-100">
            <Camera className="size-5 text-white" />
          </span>
        )}

        {/* Loading spinner */}
        {isLoading && (
          <span className="absolute inset-0 flex items-center justify-center rounded-full bg-black/40">
            <Loader2 className="size-5 animate-spin text-white" />
          </span>
        )}
      </button>

      {/* Remove button — only shown when avatar is set and not loading */}
      {avatarUrl && !isLoading && (
        <button
          className="border-tertiary bg-primary text-tertiary hover:bg-danger hover:text-danger absolute -top-1 -right-1 flex size-5 items-center justify-center rounded-full border transition-colors"
          onClick={(e) => {
            e.stopPropagation()
            onRemove()
          }}
          title="Remove avatar"
          type="button"
        >
          <X className="size-3" />
        </button>
      )}
    </div>
  )
}
