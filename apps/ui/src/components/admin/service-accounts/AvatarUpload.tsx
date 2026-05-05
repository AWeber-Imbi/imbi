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
    <div className="relative flex-shrink-0">
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
        className="group relative h-14 w-14 overflow-hidden rounded-full border border-tertiary bg-secondary transition-opacity disabled:cursor-not-allowed disabled:opacity-60"
        disabled={isLoading}
        onClick={() => fileInputRef.current?.click()}
        title="Upload avatar"
        type="button"
      >
        {avatarUrl ? (
          <img
            alt={displayName}
            className="h-full w-full object-cover"
            src={avatarUrl}
          />
        ) : (
          <span className="flex h-full w-full items-center justify-center font-mono text-sm font-medium text-secondary">
            {initials || '?'}
          </span>
        )}

        {/* Hover overlay */}
        {!isLoading && (
          <span className="absolute inset-0 flex items-center justify-center rounded-full bg-black/40 opacity-0 transition-opacity group-hover:opacity-100">
            <Camera className="h-5 w-5 text-white" />
          </span>
        )}

        {/* Loading spinner */}
        {isLoading && (
          <span className="absolute inset-0 flex items-center justify-center rounded-full bg-black/40">
            <Loader2 className="h-5 w-5 animate-spin text-white" />
          </span>
        )}
      </button>

      {/* Remove button — only shown when avatar is set and not loading */}
      {avatarUrl && !isLoading && (
        <button
          className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full border border-tertiary bg-primary text-tertiary transition-colors hover:bg-danger hover:text-danger"
          onClick={(e) => {
            e.stopPropagation()
            onRemove()
          }}
          title="Remove avatar"
          type="button"
        >
          <X className="h-3 w-3" />
        </button>
      )}
    </div>
  )
}
