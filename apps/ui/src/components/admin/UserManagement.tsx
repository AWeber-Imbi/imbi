import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Search, Filter, Edit2, Trash2, Eye, Power, Crown, Bot, AlertCircle } from 'lucide-react'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { listAdminUsers, deleteAdminUser, updateAdminUser } from '@/api/endpoints'
import type { AdminUser, AdminUserCreate } from '@/types'

interface UserManagementProps {
  isDarkMode: boolean
}

type UserFilter = 'all' | 'users' | 'service' | 'admins'
type StatusFilter = 'all' | 'active' | 'inactive'

export function UserManagement({ isDarkMode }: UserManagementProps) {
  const queryClient = useQueryClient()
  const [searchQuery, setSearchQuery] = useState('')
  const [userFilter, setUserFilter] = useState<UserFilter>('all')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [selectedEmails, setSelectedEmails] = useState<Set<string>>(new Set())

  // Fetch users from API
  const { data: users = [], isLoading, error } = useQuery({
    queryKey: ['adminUsers'],
    queryFn: () => listAdminUsers(),
  })

  // Delete user mutation
  const deleteMutation = useMutation({
    mutationFn: deleteAdminUser,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminUsers'] })
    },
    onError: (error: any) => {
      alert(`Failed to delete user: ${error.response?.data?.detail || error.message}`)
    }
  })

  // Toggle active mutation
  const toggleActiveMutation = useMutation({
    mutationFn: ({ email, user }: { email: string, user: AdminUserCreate }) =>
      updateAdminUser(email, user),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminUsers'] })
    },
    onError: (error: any) => {
      alert(`Failed to update user: ${error.response?.data?.detail || error.message}`)
    }
  })

  // Filter users locally (since API only supports is_active and is_admin filters)
  const filteredUsers = users.filter(user => {
    // Search filter
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      const matches =
        user.email.toLowerCase().includes(query) ||
        user.display_name.toLowerCase().includes(query)
      if (!matches) return false
    }

    // Type filter
    if (userFilter === 'admins' && !user.is_admin) return false
    if (userFilter === 'service' && !user.is_service_account) return false
    if (userFilter === 'users' && (user.is_admin || user.is_service_account)) return false

    // Status filter
    if (statusFilter === 'active' && !user.is_active) return false
    if (statusFilter === 'inactive' && user.is_active) return false

    return true
  })

  const handleToggleActive = (user: AdminUser) => {
    toggleActiveMutation.mutate({
      email: user.email,
      user: {
        email: user.email,
        display_name: user.display_name,
        is_active: !user.is_active,
        is_admin: user.is_admin,
        is_service_account: user.is_service_account,
      }
    })
  }

  const handleDelete = (email: string) => {
    if (confirm('Are you sure you want to delete this user? This action cannot be undone.')) {
      deleteMutation.mutate(email)
    }
  }

  const handleBulkActivate = (activate: boolean) => {
    // TODO: Implement when bulk API endpoints are available
    alert(`Bulk ${activate ? 'activation' : 'deactivation'} will be available once the API endpoints are implemented`)
    setSelectedEmails(new Set())
  }

  const handleBulkDelete = () => {
    // TODO: Implement when bulk API endpoints are available
    alert('Bulk operations will be available once the API endpoints are implemented')
    setSelectedEmails(new Set())
  }

  const toggleSelection = (email: string) => {
    const newSelection = new Set(selectedEmails)
    if (newSelection.has(email)) {
      newSelection.delete(email)
    } else {
      newSelection.add(email)
    }
    setSelectedEmails(newSelection)
  }

  const toggleSelectAll = () => {
    if (selectedEmails.size === filteredUsers.length) {
      setSelectedEmails(new Set())
    } else {
      setSelectedEmails(new Set(filteredUsers.map(u => u.email)))
    }
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

  const getGroupNames = (user: AdminUser): string => {
    if (!user.groups || user.groups.length === 0) return '-'
    return user.groups.map(g => g.name).join(', ')
  }

  // Loading state
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
          Loading users...
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
          <div className="font-medium">Failed to load users</div>
          <div className="text-sm mt-1">{error instanceof Error ? error.message : 'An error occurred'}</div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header with Actions */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className={`text-xl font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
            Users
          </h2>
          <p className={`mt-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
            Manage user accounts, service accounts, and administrators
          </p>
        </div>
        <Button
          onClick={() => alert('Create user functionality coming soon!')}
          className="bg-[#2A4DD0] hover:bg-blue-700 text-white gap-2"
        >
          <Plus className="w-4 h-4" />
          Create New User
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
              placeholder="Search by email or name..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={`pl-9 ${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''}`}
            />
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Filter className={`w-4 h-4 ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`} />
          <select
            value={userFilter}
            onChange={(e) => setUserFilter(e.target.value as UserFilter)}
            className={`px-3 py-2 rounded-lg border text-sm ${
              isDarkMode
                ? 'bg-gray-700 border-gray-600 text-white'
                : 'bg-white border-gray-300 text-gray-900'
            }`}
          >
            <option value="all">All Types</option>
            <option value="users">Regular Users</option>
            <option value="service">Service Accounts</option>
            <option value="admins">Administrators</option>
          </select>

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

      {/* Bulk Actions */}
      {selectedEmails.size > 0 && (
        <div className={`flex items-center justify-between p-4 rounded-lg border ${
          isDarkMode ? 'bg-blue-900/20 border-blue-700' : 'bg-blue-50 border-blue-200'
        }`}>
          <span className={`text-sm ${isDarkMode ? 'text-blue-300' : 'text-blue-900'}`}>
            {selectedEmails.size} user(s) selected
          </span>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleBulkActivate(true)}
              className={isDarkMode ? 'border-gray-600 text-gray-300 hover:bg-gray-700' : ''}
            >
              Activate Selected
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleBulkActivate(false)}
              className={isDarkMode ? 'border-gray-600 text-gray-300 hover:bg-gray-700' : ''}
            >
              Deactivate Selected
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleBulkDelete}
              className={isDarkMode
                ? 'border-red-700 text-red-400 hover:bg-red-900/20'
                : 'border-red-300 text-red-700 hover:bg-red-50'
              }
            >
              Delete Selected
            </Button>
          </div>
        </div>
      )}

      {/* Users Table */}
      <div className={`rounded-lg border overflow-hidden ${
        isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
      }`}>
        <table className="w-full">
          <thead className={`${isDarkMode ? 'bg-gray-750 border-b border-gray-700' : 'bg-gray-50 border-b border-gray-200'}`}>
            <tr>
              <th className="w-12 px-4 py-3">
                <input
                  type="checkbox"
                  checked={selectedEmails.size === filteredUsers.length && filteredUsers.length > 0}
                  onChange={toggleSelectAll}
                  className="rounded"
                />
              </th>
              <th className={`px-4 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                User
              </th>
              <th className={`px-4 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                Email
              </th>
              <th className={`px-4 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                Type
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
            {filteredUsers.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-12 text-center">
                  <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
                    {searchQuery || userFilter !== 'all' || statusFilter !== 'all'
                      ? 'No users match your filters'
                      : 'No users created yet'}
                  </div>
                </td>
              </tr>
            ) : (
              filteredUsers.map((user) => (
                <tr
                  key={user.email}
                  className={`${isDarkMode ? 'hover:bg-gray-750' : 'hover:bg-gray-50'} ${
                    !user.is_active ? 'opacity-60' : ''
                  }`}
                >
                  <td className="px-4 py-3">
                    <input
                      type="checkbox"
                      checked={selectedEmails.has(user.email)}
                      onChange={() => toggleSelection(user.email)}
                      className="rounded"
                    />
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      {user.avatar_url ? (
                        <img
                          src={user.avatar_url}
                          alt={user.display_name}
                          className="w-8 h-8 rounded-full"
                        />
                      ) : (
                        <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium ${
                          isDarkMode ? 'bg-gray-700 text-gray-300' : 'bg-gray-200 text-gray-600'
                        }`}>
                          {user.display_name.charAt(0).toUpperCase()}
                        </div>
                      )}
                      <div>
                        <div className={`text-sm font-medium ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
                          {user.display_name}
                        </div>
                        <div className={`text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                          {getGroupNames(user)}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td className={`px-4 py-3 text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                    {user.email}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      {user.is_admin && (
                        <span className={`inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-medium ${
                          isDarkMode ? 'bg-red-900/30 text-red-400' : 'bg-red-100 text-red-700'
                        }`}>
                          <Crown className="w-3 h-3" />
                          Admin
                        </span>
                      )}
                      {user.is_service_account && (
                        <span className={`inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-medium ${
                          isDarkMode ? 'bg-purple-900/30 text-purple-400' : 'bg-purple-100 text-purple-700'
                        }`}>
                          <Bot className="w-3 h-3" />
                          Service
                        </span>
                      )}
                      {!user.is_admin && !user.is_service_account && (
                        <span className={`px-2 py-1 rounded text-xs font-medium ${
                          isDarkMode ? 'bg-blue-900/30 text-blue-400' : 'bg-blue-100 text-blue-700'
                        }`}>
                          User
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-center">
                    <button
                      onClick={() => handleToggleActive(user)}
                      disabled={toggleActiveMutation.isPending}
                      className={`inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium ${
                        user.is_active
                          ? isDarkMode
                            ? 'bg-green-900/30 text-green-400'
                            : 'bg-green-100 text-green-700'
                          : isDarkMode
                            ? 'bg-gray-700 text-gray-400'
                            : 'bg-gray-100 text-gray-600'
                      }`}
                    >
                      <Power className="w-3 h-3" />
                      {user.is_active ? 'Active' : 'Inactive'}
                    </button>
                  </td>
                  <td className={`px-4 py-3 text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                    {formatDate(user.last_login)}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        onClick={() => alert('View user functionality coming soon!')}
                        className={`p-1.5 rounded ${
                          isDarkMode ? 'text-gray-400 hover:text-gray-200 hover:bg-gray-700' : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                        }`}
                        title="View"
                      >
                        <Eye className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => alert('Edit user functionality coming soon!')}
                        className={`p-1.5 rounded ${
                          isDarkMode ? 'text-gray-400 hover:text-gray-200 hover:bg-gray-700' : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                        }`}
                        title="Edit"
                      >
                        <Edit2 className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => handleDelete(user.email)}
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
      {filteredUsers.length > 0 && (
        <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
          Showing {filteredUsers.length} of {users.length} user(s)
        </div>
      )}
    </div>
  )
}
