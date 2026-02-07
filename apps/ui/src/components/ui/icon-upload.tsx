import { useState, useRef } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Upload, X, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { uploadFile, getUploadThumbnailUrl, deleteUpload } from '@/api/endpoints'

interface IconUploadProps {
  value?: string
  onChange: (value: string) => void
  isDarkMode: boolean
  maxSizeKB?: number
}

export function IconUpload({ value, onChange, isDarkMode, maxSizeKB = 500 }: IconUploadProps) {
  const [error, setError] = useState<string>('')
  const fileInputRef = useRef<HTMLInputElement>(null)

  const uploadMutation = useMutation({
    mutationFn: uploadFile,
  })

  const deleteMutation = useMutation({
    mutationFn: deleteUpload,
  })

  const isImageUrl = value && value.length > 0

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setError('')

    if (!file.type.startsWith('image/')) {
      setError('Please upload an image file')
      return
    }

    const fileSizeKB = file.size / 1024
    if (fileSizeKB > maxSizeKB) {
      setError(`File size must be under ${maxSizeKB}KB (current: ${Math.round(fileSizeKB)}KB)`)
      return
    }

    try {
      const upload = await uploadMutation.mutateAsync(file)
      onChange(`/uploads/${upload.id}`)
    } catch {
      setError('Failed to upload image')
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
          }
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
      {isImageUrl && (
        <div className={`inline-flex items-center gap-3 p-3 rounded-lg border ${
          isDarkMode ? 'bg-gray-700 border-gray-600' : 'bg-gray-50 border-gray-200'
        }`}>
          <div className="w-12 h-12 rounded-lg flex items-center justify-center overflow-hidden bg-white">
            <img src={getThumbnailSrc(value)} alt="Icon preview" className="w-full h-full object-cover" />
          </div>
          <div className={`text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}>
            Uploaded icon
          </div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={handleRemove}
            className={isDarkMode ? 'text-red-400 hover:text-red-300 hover:bg-red-900/20' : 'text-red-600'}
          >
            <X className="w-4 h-4" />
          </Button>
        </div>
      )}

      {!value && (
        <div>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            onChange={handleFileChange}
            className="hidden"
          />
          <Button
            type="button"
            variant="outline"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploadMutation.isPending}
            className={`w-full ${isDarkMode ? 'border-gray-600 text-gray-300 hover:bg-gray-700' : ''}`}
          >
            {uploadMutation.isPending ? (
              <>
                <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin mr-2" />
                Uploading...
              </>
            ) : (
              <>
                <Upload className="w-4 h-4 mr-2" />
                Upload Image
              </>
            )}
          </Button>
          <p className={`text-xs mt-1.5 ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
            PNG, JPG, or SVG - Max {maxSizeKB}KB
          </p>
        </div>
      )}

      {error && (
        <div className={`p-3 rounded-lg flex items-start gap-2 ${
          isDarkMode
            ? 'bg-red-900/20 text-red-400 border border-red-700'
            : 'bg-red-50 text-red-600 border border-red-200'
        }`}>
          <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
          <div className="text-xs">{error}</div>
        </div>
      )}
    </div>
  )
}
