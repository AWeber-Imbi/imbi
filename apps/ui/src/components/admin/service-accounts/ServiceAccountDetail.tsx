import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Edit2, Power, Clock, Mail, Calendar, Key, Copy, Plus, Trash2, AlertCircle } from 'lucide-react'
import { Button } from '../../ui/button'
import { listApiKeys, createApiKey, deleteApiKey } from '@/api/endpoints'
import type { AdminUser, ApiKey, ApiKeyCreated } from '@/types'

interface ServiceAccountDetailProps {
  account: AdminUser
  onEdit: () => void
  onBack: () => void
  isDarkMode: boolean
}

export function ServiceAccountDetail({ account, onEdit, onBack, isDarkMode }: ServiceAccountDetailProps) {
  const queryClient = useQueryClient()
  const [newKeyName, setNewKeyName] = useState('')
  const [showCreateKey, setShowCreateKey] = useState(false)
  const [newlyCreatedKey, setNewlyCreatedKey] = useState<ApiKeyCreated | null>(null)
  const [copiedKeyId, setCopiedKeyId] = useState<string | null>(null)

  // Fetch API keys
  const { data: apiKeys = [], isLoading: keysLoading, error: keysError } = useQuery({
    queryKey: ['apiKeys', account.email],
    queryFn: () => listApiKeys(account.email),
  })

  // Create API key mutation
  const createKeyMutation = useMutation({
    mutationFn: (name: string) => createApiKey(account.email, name),
    onSuccess: (data: ApiKeyCreated) => {
      setNewlyCreatedKey(data)
      setShowCreateKey(false)
      setNewKeyName('')
      queryClient.invalidateQueries({ queryKey: ['apiKeys', account.email] })
    },
    onError: (error: any) => {
      alert(`Failed to create API key: ${error.response?.data?.detail || error.message}`)
    }
  })

  // Delete API key mutation
  const deleteKeyMutation = useMutation({
    mutationFn: (keyId: string) => deleteApiKey(account.email, keyId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['apiKeys', account.email] })
    },
    onError: (error: any) => {
      alert(`Failed to delete API key: ${error.response?.data?.detail || error.message}`)
    }
  })

  const formatDate = (dateString?: string | null) => {
    if (!dateString) return 'Never'
    return new Date(dateString).toLocaleString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
  }

  const copyToClipboard = async (text: string, id: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedKeyId(id)
      setTimeout(() => setCopiedKeyId(null), 2000)
    } catch {
      alert('Failed to copy to clipboard')
    }
  }

  const handleCreateKey = () => {
    const name = newKeyName.trim() || 'default'
    createKeyMutation.mutate(name)
  }

  const handleDeleteKey = (keyId: string) => {
    if (confirm('Are you sure you want to delete this API key? This action cannot be undone.')) {
      deleteKeyMutation.mutate(keyId)
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="outline" onClick={onBack} className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}>
            <ArrowLeft className="w-4 h-4 mr-2" />
            Back
          </Button>
          <div>
            <h2 className={`text-2xl ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
              {account.display_name}
            </h2>
            <p className={`mt-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
              {account.email}
            </p>
          </div>
        </div>
        <Button onClick={onEdit} className="bg-[#2A4DD0] hover:bg-blue-700 text-white">
          <Edit2 className="w-4 h-4 mr-2" />
          Edit Account
        </Button>
      </div>

      {/* Account Status */}
      <div className={`p-6 rounded-lg border ${
        isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
      }`}>
        <h3 className={`mb-4 font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
          Account Status
        </h3>
        <div className="flex items-center gap-6">
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded ${
            account.is_active
              ? isDarkMode ? 'bg-green-900/30 text-green-400' : 'bg-green-100 text-green-700'
              : isDarkMode ? 'bg-gray-700 text-gray-400' : 'bg-gray-100 text-gray-600'
          }`}>
            <Power className="w-4 h-4" />
            {account.is_active ? 'Active' : 'Inactive'}
          </div>
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded ${
            isDarkMode ? 'bg-purple-900/30 text-purple-400' : 'bg-purple-100 text-purple-700'
          }`}>
            Service Account
          </div>
        </div>
      </div>

      {/* API Keys */}
      <div className={`p-6 rounded-lg border ${
        isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
      }`}>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Key className={`w-5 h-5 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`} />
            <h3 className={`font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
              API Keys
            </h3>
          </div>
          <Button
            onClick={() => setShowCreateKey(!showCreateKey)}
            variant="outline"
            size="sm"
            className={isDarkMode ? 'border-gray-600 text-gray-300 hover:bg-gray-700' : ''}
          >
            <Plus className="w-4 h-4 mr-2" />
            Create API Key
          </Button>
        </div>

        {/* Create Key Form */}
        {showCreateKey && (
          <div className={`mb-4 p-4 rounded-lg border ${
            isDarkMode ? 'bg-gray-750 border-gray-600' : 'bg-gray-50 border-gray-200'
          }`}>
            <div className="flex items-end gap-3">
              <div className="flex-1">
                <label className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                  Key Name
                </label>
                <input
                  type="text"
                  value={newKeyName}
                  onChange={(e) => setNewKeyName(e.target.value)}
                  placeholder="e.g., production, staging"
                  className={`w-full px-3 py-2 rounded-lg border text-sm ${
                    isDarkMode
                      ? 'bg-gray-700 border-gray-600 text-white placeholder:text-gray-400'
                      : 'bg-white border-gray-300 text-gray-900 placeholder:text-gray-500'
                  }`}
                />
              </div>
              <Button
                onClick={handleCreateKey}
                disabled={createKeyMutation.isPending}
                className="bg-[#2A4DD0] hover:bg-blue-700 text-white"
              >
                {createKeyMutation.isPending ? 'Creating...' : 'Create'}
              </Button>
              <Button
                variant="outline"
                onClick={() => {
                  setShowCreateKey(false)
                  setNewKeyName('')
                }}
                className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}
              >
                Cancel
              </Button>
            </div>
          </div>
        )}

        {/* Newly Created Key Banner */}
        {newlyCreatedKey && (
          <div className={`mb-4 p-4 rounded-lg border ${
            isDarkMode ? 'bg-green-900/20 border-green-700' : 'bg-green-50 border-green-200'
          }`}>
            <div className={`font-medium mb-2 ${isDarkMode ? 'text-green-400' : 'text-green-800'}`}>
              API Key Created - Copy it now, it will not be shown again!
            </div>
            <div className="flex items-center gap-2">
              <code className={`flex-1 text-sm px-3 py-2 rounded border ${
                isDarkMode ? 'bg-gray-800 border-gray-600 text-green-300' : 'bg-white border-gray-200 text-green-700'
              }`}>
                {newlyCreatedKey.token}
              </code>
              <button
                onClick={() => copyToClipboard(newlyCreatedKey.token, 'new')}
                className={`p-2 rounded-lg ${
                  copiedKeyId === 'new'
                    ? 'bg-green-600 text-white'
                    : isDarkMode ? 'hover:bg-gray-700 text-gray-400' : 'hover:bg-gray-200 text-gray-600'
                }`}
                title="Copy to clipboard"
              >
                <Copy className="w-4 h-4" />
              </button>
            </div>
            <button
              onClick={() => setNewlyCreatedKey(null)}
              className={`text-sm mt-2 ${isDarkMode ? 'text-green-400 hover:text-green-300' : 'text-green-700 hover:text-green-800'}`}
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Keys List */}
        {keysLoading ? (
          <div className={`text-sm py-4 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
            Loading API keys...
          </div>
        ) : keysError ? (
          <div className={`flex items-center gap-2 p-3 rounded-lg ${
            isDarkMode ? 'bg-red-900/20 text-red-400' : 'bg-red-50 text-red-700'
          }`}>
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            <span className="text-sm">Failed to load API keys</span>
          </div>
        ) : apiKeys.length === 0 ? (
          <div className={`text-center py-8 ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
            <Key className={`w-8 h-8 mx-auto mb-2 ${isDarkMode ? 'text-gray-600' : 'text-gray-400'}`} />
            <div>No API keys created yet</div>
            <div className="text-sm mt-1">Create an API key to enable programmatic access</div>
          </div>
        ) : (
          <div className="space-y-2">
            {apiKeys.map((key: ApiKey) => (
              <div
                key={key.id}
                className={`flex items-center justify-between p-3 rounded-lg border ${
                  isDarkMode ? 'bg-gray-750 border-gray-600' : 'bg-gray-50 border-gray-200'
                }`}
              >
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className={`text-sm font-medium ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
                      {key.name}
                    </span>
                    <code className={`text-xs px-2 py-0.5 rounded ${
                      isDarkMode ? 'bg-gray-700 text-gray-400' : 'bg-gray-100 text-gray-600'
                    }`}>
                      {key.prefix}...
                    </code>
                  </div>
                  <div className={`text-xs mt-1 ${isDarkMode ? 'text-gray-500' : 'text-gray-500'}`}>
                    Created {formatDate(key.created_at)}
                    {key.last_used_at && ` | Last used ${formatDate(key.last_used_at)}`}
                    {key.expires_at && ` | Expires ${formatDate(key.expires_at)}`}
                  </div>
                </div>
                <button
                  onClick={() => handleDeleteKey(key.id)}
                  disabled={deleteKeyMutation.isPending}
                  className={`p-1.5 rounded ${
                    isDarkMode ? 'text-red-400 hover:text-red-300 hover:bg-gray-700' : 'text-red-600 hover:text-red-700 hover:bg-gray-100'
                  }`}
                  title="Delete API key"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Basic Information */}
      <div className={`p-6 rounded-lg border ${
        isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
      }`}>
        <h3 className={`mb-4 font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
          Basic Information
        </h3>

        <div className="grid grid-cols-2 gap-6">
          <div>
            <div className={`flex items-center gap-2 text-sm mb-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
              <Mail className="w-4 h-4" />
              Email
            </div>
            <div className={isDarkMode ? 'text-white' : 'text-gray-900'}>
              {account.email}
            </div>
          </div>

          <div>
            <div className={`flex items-center gap-2 text-sm mb-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
              Display Name
            </div>
            <div className={isDarkMode ? 'text-white' : 'text-gray-900'}>
              {account.display_name}
            </div>
          </div>

          <div>
            <div className={`flex items-center gap-2 text-sm mb-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
              <Calendar className="w-4 h-4" />
              Created
            </div>
            <div className={isDarkMode ? 'text-white' : 'text-gray-900'}>
              {formatDate(account.created_at)}
            </div>
          </div>

          <div>
            <div className={`flex items-center gap-2 text-sm mb-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
              <Clock className="w-4 h-4" />
              Last Login
            </div>
            <div className={isDarkMode ? 'text-white' : 'text-gray-900'}>
              {formatDate(account.last_login)}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
