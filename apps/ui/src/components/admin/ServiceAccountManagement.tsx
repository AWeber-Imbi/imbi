import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Search, Filter, Trash2, Power, Bot, AlertCircle } from 'lucide-react'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { ServiceAccountForm } from './service-accounts/ServiceAccountForm'
import { ServiceAccountDetail } from './service-accounts/ServiceAccountDetail'
import { listAdminUsers, createAdminUser, updateAdminUser, deleteAdminUser } from '@/api/endpoints'
import type { AdminUser, AdminUserCreate } from '@/types'

interface ServiceAccountManagementProps {
  isDarkMode: boolean
}

type ViewMode = 'list' | 'create' | 'edit' | 'detail'
type StatusFilter = 'all' | 'active' | 'inactive'

export function ServiceAccountManagement({ isDarkMode }: ServiceAccountManagementProps) {
  const queryClient = useQueryClient()
  const [viewMode, setViewMode] = useState<ViewMode>('list')
  const [selectedAccount, setSelectedAccount] = useState<AdminUser | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')

  // Fetch all users and filter for service accounts
  const { data: users = [], isLoading, error } = useQuery({
    queryKey: ['adminUsers'],
    queryFn: () => listAdminUsers(),
  })

  const serviceAccounts = users.filter(user => user.is_service_account === true)

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: deleteAdminUser,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminUsers'] })
    },
    onError: (error: any) => {
      alert(`Failed to delete service account: ${error.response?.data?.detail || error.message}`)
    }
  })

  // Create mutation
  const createMutation = useMutation({
    mutationFn: createAdminUser,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminUsers'] })
      setViewMode('list')
      setSelectedAccount(null)
    },
    onError: (error: any) => {
      console.error('Failed to create service account:', error)
    }
  })

  // Update mutation
  const updateMutation = useMutation({
    mutationFn: ({ email, user }: { email: string, user: AdminUserCreate }) =>
      updateAdminUser(email, user),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminUsers'] })
      setViewMode('list')
      setSelectedAccount(null)
    },
    onError: (error: any) => {
      console.error('Failed to update service account:', error)
    }
  })

  // Filter service accounts
  const filteredAccounts = serviceAccounts.filter(account => {
    if (statusFilter === 'active' && !account.is_active) return false
    if (statusFilter === 'inactive' && account.is_active) return false

    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      return (
        account.display_name.toLowerCase().includes(query) ||
        account.email.toLowerCase().includes(query)
      )
    }

    return true
  })

  const handleDelete = (email: string) => {
    const account = serviceAccounts.find(a => a.email === email)
    if (confirm(`Are you sure you want to delete "${account?.display_name}"? This will revoke all API access and cannot be undone.`)) {
      deleteMutation.mutate(email)
    }
  }

  const handleViewClick = (account: AdminUser) => {
    setSelectedAccount(account)
    setViewMode('detail')
  }

  const handleEditClick = (account: AdminUser) => {
    setSelectedAccount(account)
    setViewMode('edit')
  }

  const handleSave = (userData: AdminUserCreate) => {
    if (viewMode === 'create') {
      createMutation.mutate(userData)
    } else if (selectedAccount) {
      updateMutation.mutate({ email: selectedAccount.email, user: userData })
    }
  }

  const handleCancel = () => {
    setViewMode('list')
    setSelectedAccount(null)
  }

  const formatDate = (dateString?: string | null) => {
    if (!dateString) return 'Never'
    return new Date(dateString).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
  }

  // Loading state
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
          Loading service accounts...
        </div>
      </div>
    )
  }

  // Error state
  if (error) {
    return (
      <div className={`flex items-center gap-3 p-4 rounded-lg border ${
        isDarkMode ? 'bg-red-900/20 border-red-700 text-red-400' : 'bg-red-50 border-red-200 text-red-700'
      }`}>
        <AlertCircle className="w-5 h-5 flex-shrink-0" />
        <div>
          <div className="font-medium">Failed to load service accounts</div>
          <div className="text-sm mt-1">{error instanceof Error ? error.message : 'An error occurred'}</div>
        </div>
      </div>
    )
  }

  // View mode: Create or Edit
  if (viewMode === 'create' || viewMode === 'edit') {
    return (
      <ServiceAccountForm
        account={selectedAccount}
        onSave={handleSave}
        onCancel={handleCancel}
        isDarkMode={isDarkMode}
        isLoading={createMutation.isPending || updateMutation.isPending}
        error={createMutation.error || updateMutation.error}
      />
    )
  }

  // View mode: Detail
  if (viewMode === 'detail' && selectedAccount) {
    return (
      <ServiceAccountDetail
        account={selectedAccount}
        onEdit={() => handleEditClick(selectedAccount)}
        onBack={handleCancel}
        isDarkMode={isDarkMode}
      />
    )
  }

  // View mode: List (default)
  return (
    <div className="space-y-6">
      {/* Header with Actions */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className={`text-xl font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
            Service Accounts
          </h2>
          <p className={`mt-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
            Manage API access for automated services and integrations
          </p>
        </div>
        <Button
          onClick={() => {
            setSelectedAccount(null)
            setViewMode('create')
          }}
          className="bg-[#2A4DD0] hover:bg-blue-700 text-white gap-2"
        >
          <Plus className="w-4 h-4" />
          Create Service Account
        </Button>
      </div>

      {/* Filters and Search */}
      <div className={`flex flex-wrap items-center gap-4 p-4 rounded-lg border ${
        isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
      }`}>
        <div className="flex-1 min-w-[300px]">
          <div className="relative">
            <Search className={`absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 ${
              isDarkMode ? 'text-gray-400' : 'text-gray-500'
            }`} />
            <Input
              placeholder="Search by name or email..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={`pl-9 ${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''}`}
            />
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Filter className={`w-4 h-4 ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`} />
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
            className={`px-3 py-2 rounded-lg border text-sm ${
              isDarkMode
                ? 'bg-gray-700 border-gray-600 text-white'
                : 'bg-white border-gray-300 text-gray-900'
            }`}
          >
            <option value="all">All Status</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </div>
      </div>

      {/* Service Accounts Table */}
      <div className={`rounded-lg border overflow-hidden ${
        isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
      }`}>
        <table className="w-full">
          <thead className={`${isDarkMode ? 'bg-gray-750 border-b border-gray-700' : 'bg-gray-50 border-b border-gray-200'}`}>
            <tr>
              <th className={`px-4 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                Service Account
              </th>
              <th className={`px-4 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                Email
              </th>
              <th className={`px-4 py-3 text-center text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                Status
              </th>
              <th className={`px-4 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                Last Login
              </th>
              <th className={`px-4 py-3 text-right text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                Actions
              </th>
            </tr>
          </thead>
          <tbody className={isDarkMode ? 'divide-y divide-gray-700' : 'divide-y divide-gray-200'}>
            {filteredAccounts.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-12 text-center">
                  <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
                    {searchQuery || statusFilter !== 'all'
                      ? 'No service accounts match your filters'
                      : 'No service accounts created yet'}
                  </div>
                  {!searchQuery && statusFilter === 'all' && (
                    <Button
                      onClick={() => {
                        setSelectedAccount(null)
                        setViewMode('create')
                      }}
                      className="mt-4 bg-[#2A4DD0] hover:bg-blue-700 text-white"
                    >
                      Create Your First Service Account
                    </Button>
                  )}
                </td>
              </tr>
            ) : (
              filteredAccounts.map((account) => (
                <tr
                  key={account.email}
                  onClick={() => handleViewClick(account)}
                  className={`cursor-pointer ${isDarkMode ? 'hover:bg-gray-750' : 'hover:bg-gray-50'} ${
                    !account.is_active ? 'opacity-60' : ''
                  }`}
                >
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <div className={`w-8 h-8 rounded-full flex items-center justify-center ${
                        isDarkMode ? 'bg-purple-900/30' : 'bg-purple-100'
                      }`}>
                        <Bot className={`w-4 h-4 ${isDarkMode ? 'text-purple-400' : 'text-purple-600'}`} />
                      </div>
                      <div>
                        <div className={`text-sm font-medium ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
                          {account.display_name}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td className={`px-4 py-3 text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                    {account.email}
                  </td>
                  <td className="px-4 py-3 text-center">
                    <span className={`inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium ${
                      account.is_active
                        ? isDarkMode
                          ? 'bg-green-900/30 text-green-400'
                          : 'bg-green-100 text-green-700'
                        : isDarkMode
                          ? 'bg-gray-700 text-gray-400'
                          : 'bg-gray-100 text-gray-600'
                    }`}>
                      <Power className="w-3 h-3" />
                      {account.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td className={`px-4 py-3 text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                    {formatDate(account.last_login)}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          handleDelete(account.email)
                        }}
                        disabled={deleteMutation.isPending}
                        className={`p-1.5 rounded ${
                          isDarkMode ? 'text-red-400 hover:text-red-300 hover:bg-gray-700' : 'text-red-600 hover:text-red-700 hover:bg-gray-100'
                        }`}
                        title="Delete"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Summary */}
      {filteredAccounts.length > 0 && (
        <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
          Showing {filteredAccounts.length} of {serviceAccounts.length} service account(s)
        </div>
      )}
    </div>
  )
}
