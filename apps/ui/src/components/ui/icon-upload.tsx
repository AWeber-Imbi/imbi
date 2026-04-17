import { useState, useRef } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Upload, X, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  uploadFile,
  getUploadThumbnailUrl,
  deleteUpload,
} from '@/api/endpoints'

interface IconUploadProps {
  value?: string
  onChange: (value: string) => void
  maxSizeKB?: number
}

export function IconUpload({
  value,
  onChange,
  maxSizeKB = 500,
}: IconUploadProps) {
  const [error, setError] = useState<string>('')
  const fileInputRef = useRef<HTMLInputElement>(null)

  const uploadMutation = useMutation({
    mutationFn: uploadFile,
  })

  const deleteMutation = useMutation({
    mutationFn: deleteUpload,
  })

  const isImageUrl =
    value != null && (value.startsWith('/') || value.startsWith('http'))

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const input = e.target
    const file = input.files?.[0]
    if (!file) return

    setError('')

    const allowedTypes = ['image/png', 'image/jpeg', 'image/svg+xml']
    if (!allowedTypes.includes(file.type)) {
      setError('Please upload a PNG, JPG, or SVG image')
      input.value = ''
      return
    }

    const fileSizeKB = file.size / 1024
    if (fileSizeKB > maxSizeKB) {
      setError(
        `File size must be under ${maxSizeKB}KB (current: ${Math.round(fileSizeKB)}KB)`,
      )
      input.value = ''
      return
    }

    try {
      const upload = await uploadMutation.mutateAsync(file)
      onChange(`/uploads/${upload.id}`)
    } catch {
      setError('Failed to upload image')
    } finally {
      input.value = ''
    }
  }

  const handleRemove = () => {
    // Best-effort cleanup: delete the uploaded file from storage
    if (value) {
      const match = value.match(/\/uploads\/(.+)$/)
      if (match) {
        deleteMutation.mutate(match[1], {
          onError: () => {
            // Ignore delete errors - the file may already be gone
          },
        })
      }
    }
    onChange('')
    setError('')
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  // Extract upload ID from URL path for thumbnail
  const getThumbnailSrc = (url: string): string => {
    const match = url.match(/\/uploads\/(.+)$/)
    if (match) {
      return getUploadThumbnailUrl(match[1])
    }
    return url
  }

  return (
    <div className="space-y-3">
      {isImageUrl && value && (
        <div
          className={`inline-flex items-center gap-3 rounded-lg border p-3 ${'border-input bg-secondary'}`}
        >
          <div className="flex h-12 w-12 items-center justify-center overflow-hidden rounded-lg bg-white">
            <img
              src={getThumbnailSrc(value)}
              alt="Icon preview"
              className="h-full w-full object-cover"
            />
          </div>
          <div className={'text-sm text-secondary'}>Uploaded icon</div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={handleRemove}
            aria-label="Remove uploaded icon"
            className={'text-danger hover:bg-danger'}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      )}

      {!value && (
        <div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".png,.jpg,.jpeg,.svg"
            onChange={handleFileChange}
            className="hidden"
          />
          <Button
            type="button"
            variant="outline"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploadMutation.isPending}
            className={'w-full'}
          >
            {uploadMutation.isPending ? (
              <>
                <div className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                Uploading...
              </>
            ) : (
              <>
                <Upload className="mr-2 h-4 w-4" />
                Upload Image
              </>
            )}
          </Button>
          <p className={'mt-1.5 text-xs text-tertiary'}>
            PNG, JPG, or SVG - Max {maxSizeKB}KB
          </p>
        </div>
      )}

      {error && (
        <div
          className={`flex items-start gap-2 rounded-lg p-3 ${'border border-danger bg-danger text-danger'}`}
        >
          <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
          <div className="text-xs">{error}</div>
        </div>
      )}
    </div>
  )
}
