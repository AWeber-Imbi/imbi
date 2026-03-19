import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Plus,
  Search,
  Edit2,
  Trash2,
  Power,
  Crown,
  AlertCircle,
} from 'lucide-react'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { Gravatar } from '../ui/gravatar'
import { UserForm } from './users/UserForm'
import { UserDetail } from './users/UserDetail'
import { useAdminNav } from '@/hooks/useAdminNav'
import {
  listAdminUsers,
  getAdminUser,
  deleteAdminUser,
  updateAdminUser,
  createAdminUser,
} from '@/api/endpoints'
import type { AdminUser, AdminUserCreate, AdminUserUpdate } from '@/types'

interface UserManagementProps {
  isDarkMode: boolean
}

type UserFilter = 'all' | 'users' | 'admins'
type StatusFilter = 'all' | 'active' | 'inactive'

export function UserManagement({ isDarkMode }: UserManagementProps) {
  const queryClient = useQueryClient()
  const {
    viewMode,
    slug: selectedUserEmail,
    goToList,
    goToCreate,
    goToDetail,
    goToEdit,
  } = useAdminNav()
  const [searchQuery, setSearchQuery] = useState('')
  const [userFilter, setUserFilter] = useState<UserFilter>('all')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [selectedEmails, setSelectedEmails] = useState<Set<string>>(new Set())

  // Fetch users from API
  const {
    data: users = [],
    isLoading,
    error,
  } = useQuery({
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
      alert(
        `Failed to delete user: ${error.response?.data?.detail || error.message}`,
      )
    },
  })

  // Toggle active mutation
  const toggleActiveMutation = useMutation({
    mutationFn: ({ email, user }: { email: string; user: AdminUserUpdate }) =>
      updateAdminUser(email, user),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminUsers'] })
    },
    onError: (error: any) => {
      alert(
        `Failed to update user: ${error.response?.data?.detail || error.message}`,
      )
    },
  })

  // Create user mutation
  const createMutation = useMutation({
    mutationFn: createAdminUser,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminUsers'] })
      goToList()
    },
    onError: (error: any) => {
      // Error will be displayed in the UserForm component
      console.error('Failed to create user:', error)
    },
  })

  // Update user mutation
  const updateMutation = useMutation({
    mutationFn: ({ email, user }: { email: string; user: AdminUserUpdate }) =>
      updateAdminUser(email, user),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminUsers'] })
      goToList()
    },
    onError: (error: any) => {
      // Error will be displayed in the UserForm component
      console.error('Failed to update user:', error)
    },
  })

  // Filter users locally - exclude service accounts (managed separately)
  const filteredUsers = users.filter((user) => {
    // Exclude service accounts - they have their own management section
    if (user.is_service_account) return false

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
    if (userFilter === 'users' && user.is_admin) return false

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
      },
    })
  }

  const handleDelete = (email: string) => {
    if (
      confirm(
        'Are you sure you want to delete this user? This action cannot be undone.',
      )
    ) {
      deleteMutation.mutate(email)
    }
  }

  const handleBulkActivate = (activate: boolean) => {
    // TODO: Implement when bulk API endpoints are available
    alert(
      `Bulk ${activate ? 'activation' : 'deactivation'} will be available once the API endpoints are implemented`,
    )
    setSelectedEmails(new Set())
  }

  const handleBulkDelete = () => {
    // TODO: Implement when bulk API endpoints are available
    alert(
      'Bulk operations will be available once the API endpoints are implemented',
    )
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
      setSelectedEmails(new Set(filteredUsers.map((u) => u.email)))
    }
  }

  const formatDate = (dateString?: string | null) => {
    if (!dateString) return 'Never'
    return new Date(dateString).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  const getGroupNames = (user: AdminUser): string => {
    if (!user.groups || user.groups.length === 0) return '-'
    return user.groups.map((g) => g.name).join(', ')
  }

  // Fetch full user detail (with orgs) when viewing/editing a specific user
  const { data: selectedUser = null } = useQuery({
    queryKey: ['adminUser', selectedUserEmail],
    queryFn: () => getAdminUser(selectedUserEmail!),
    enabled:
      !!selectedUserEmail && (viewMode === 'detail' || viewMode === 'edit'),
  })

  // View handlers
  const handleCreateClick = () => {
    goToCreate()
  }

  const handleEditClick = (user: AdminUser) => {
    goToEdit(user.email)
  }

  const handleViewClick = (user: AdminUser) => {
    goToDetail(user.email)
  }

  const handleSave = (userData: AdminUserCreate) => {
    if (viewMode === 'create') {
      createMutation.mutate(userData)
    } else if (selectedUser) {
      // Strip org/role fields for update — they're only for creation
      const { organization_slug: _, role_slug: __, ...updateData } = userData
      updateMutation.mutate({ email: selectedUser.email, user: updateData })
    }
  }

  const handleCancel = () => {
    goToList()
  }

  // Loading state
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div
          className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
        >
          Loading users...
        </div>
      </div>
    )
  }

  // Error state
  if (error) {
    return (
      <div
        className={`flex items-center gap-3 rounded-lg border p-4 ${
          isDarkMode
            ? 'border-red-700 bg-red-900/20 text-red-400'
            : 'border-red-200 bg-red-50 text-red-700'
        }`}
      >
        <AlertCircle className="h-5 w-5 flex-shrink-0" />
        <div>
          <div className="font-medium">Failed to load users</div>
          <div className="mt-1 text-sm">
            {error instanceof Error ? error.message : 'An error occurred'}
          </div>
        </div>
      </div>
    )
  }

  // Guard for invalid user email in URL
  if (
    (viewMode === 'edit' || viewMode === 'detail') &&
    !!selectedUserEmail &&
    !selectedUser
  ) {
    return (
      <div
        className={`rounded-lg border p-4 ${isDarkMode ? 'border-gray-700 text-gray-300' : 'border-gray-200 text-gray-700'}`}
      >
        User not found. They may have been removed.
      </div>
    )
  }

  // View mode: Create or Edit
  if (viewMode === 'create' || viewMode === 'edit') {
    return (
      <UserForm
        user={selectedUser}
        onSave={handleSave}
        onCancel={handleCancel}
        isDarkMode={isDarkMode}
        isLoading={createMutation.isPending || updateMutation.isPending}
        error={createMutation.error || updateMutation.error}
      />
    )
  }

  // View mode: Detail
  if (viewMode === 'detail' && selectedUser) {
    return (
      <UserDetail
        user={selectedUser}
        onEdit={() => handleEditClick(selectedUser)}
        onBack={handleCancel}
        isDarkMode={isDarkMode}
      />
    )
  }

  // View mode: List (default)
  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex flex-1 items-center gap-3">
          <div className="relative max-w-md flex-1">
            <Search
              className={`absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 ${
                isDarkMode ? 'text-gray-400' : 'text-gray-500'
              }`}
            />
            <Input
              placeholder="Search users..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={`pl-10 ${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''}`}
            />
          </div>
          <select
            value={userFilter}
            onChange={(e) => setUserFilter(e.target.value as UserFilter)}
            className={`rounded-lg border px-3 py-2 text-sm ${
              isDarkMode
                ? 'border-gray-600 bg-gray-700 text-white'
                : 'border-gray-300 bg-white text-gray-900'
            }`}
          >
            <option value="all">All Types</option>
            <option value="users">Regular Users</option>
            <option value="admins">Administrators</option>
          </select>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
            className={`rounded-lg border px-3 py-2 text-sm ${
              isDarkMode
                ? 'border-gray-600 bg-gray-700 text-white'
                : 'border-gray-300 bg-white text-gray-900'
            }`}
          >
            <option value="all">All Status</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </div>
        <Button
          onClick={handleCreateClick}
          className="bg-[#2A4DD0] text-white hover:bg-blue-700"
        >
          <Plus className="mr-2 h-4 w-4" />
          New User
        </Button>
      </div>

      {/* Bulk Actions */}
      {selectedEmails.size > 0 && (
        <div
          className={`flex items-center justify-between rounded-lg border p-4 ${
            isDarkMode
              ? 'border-blue-700 bg-blue-900/20'
              : 'border-blue-200 bg-blue-50'
          }`}
        >
          <span
            className={`text-sm ${isDarkMode ? 'text-blue-300' : 'text-blue-900'}`}
          >
            {selectedEmails.size} user(s) selected
          </span>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleBulkActivate(true)}
              className={
                isDarkMode
                  ? 'border-gray-600 text-gray-300 hover:bg-gray-700'
                  : ''
              }
            >
              Activate Selected
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleBulkActivate(false)}
              className={
                isDarkMode
                  ? 'border-gray-600 text-gray-300 hover:bg-gray-700'
                  : ''
              }
            >
              Deactivate Selected
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleBulkDelete}
              className={
                isDarkMode
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
      <div
        className={`overflow-hidden rounded-lg border ${
          isDarkMode
            ? 'border-gray-700 bg-gray-800'
            : 'border-gray-200 bg-white'
        }`}
      >
        <table className="w-full">
          <thead
            className={`${isDarkMode ? 'bg-gray-750 border-b border-gray-700' : 'border-b border-gray-200 bg-gray-50'}`}
          >
            <tr>
              <th className="w-12 px-4 py-3">
                <input
                  type="checkbox"
                  checked={
                    selectedEmails.size === filteredUsers.length &&
                    filteredUsers.length > 0
                  }
                  onChange={toggleSelectAll}
                  className="rounded"
                />
              </th>
              <th
                className={`px-4 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                User
              </th>
              <th
                className={`px-4 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Email
              </th>
              <th
                className={`px-4 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Type
              </th>
              <th
                className={`px-4 py-3 text-center text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Status
              </th>
              <th
                className={`px-4 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Last Login
              </th>
              <th
                className={`px-4 py-3 text-right text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Actions
              </th>
            </tr>
          </thead>
          <tbody
            className={
              isDarkMode
                ? 'divide-y divide-gray-700'
                : 'divide-y divide-gray-200'
            }
          >
            {filteredUsers.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-12 text-center">
                  <div
                    className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
                  >
                    {searchQuery ||
                    userFilter !== 'all' ||
                    statusFilter !== 'all'
                      ? 'No users match your filters'
                      : 'No users created yet'}
                  </div>
                </td>
              </tr>
            ) : (
              filteredUsers.map((user) => (
                <tr
                  key={user.email}
                  onClick={() => handleViewClick(user)}
                  className={`cursor-pointer ${isDarkMode ? 'hover:bg-gray-750' : 'hover:bg-gray-50'} ${
                    !user.is_active ? 'opacity-60' : ''
                  }`}
                >
                  <td
                    className="px-4 py-3"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <input
                      type="checkbox"
                      checked={selectedEmails.has(user.email)}
                      onChange={() => toggleSelection(user.email)}
                      className="rounded"
                    />
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <Gravatar
                        email={user.email}
                        size={32}
                        alt={user.display_name}
                        className="h-8 w-8 rounded-full"
                      />
                      <div>
                        <div
                          className={`text-sm font-medium ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
                        >
                          {user.display_name}
                        </div>
                        <div
                          className={`text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                        >
                          {getGroupNames(user)}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td
                    className={`px-4 py-3 text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
                  >
                    {user.email}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      {user.is_admin ? (
                        <span
                          className={`inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium ${
                            isDarkMode
                              ? 'bg-red-900/30 text-red-400'
                              : 'bg-red-100 text-red-700'
                          }`}
                        >
                          <Crown className="h-3 w-3" />
                          Admin
                        </span>
                      ) : (
                        <span
                          className={`rounded px-2 py-1 text-xs font-medium ${
                            isDarkMode
                              ? 'bg-blue-900/30 text-blue-400'
                              : 'bg-blue-100 text-blue-700'
                          }`}
                        >
                          User
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-center">
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        handleToggleActive(user)
                      }}
                      disabled={toggleActiveMutation.isPending}
                      className={`inline-flex items-center gap-1.5 rounded px-2 py-1 text-xs font-medium ${
                        user.is_active
                          ? isDarkMode
                            ? 'bg-green-900/30 text-green-400'
                            : 'bg-green-100 text-green-700'
                          : isDarkMode
                            ? 'bg-gray-700 text-gray-400'
                            : 'bg-gray-100 text-gray-600'
                      }`}
                    >
                      <Power className="h-3 w-3" />
                      {user.is_active ? 'Active' : 'Inactive'}
                    </button>
                  </td>
                  <td
                    className={`px-4 py-3 text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                  >
                    {formatDate(user.last_login)}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          handleEditClick(user)
                        }}
                        className={`rounded p-1.5 ${
                          isDarkMode
                            ? 'text-gray-400 hover:bg-gray-700 hover:text-gray-200'
                            : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                        }`}
                        title="Edit"
                      >
                        <Edit2 className="h-4 w-4" />
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          handleDelete(user.email)
                        }}
                        disabled={deleteMutation.isPending}
                        className={`rounded p-1.5 ${
                          isDarkMode
                            ? 'text-red-400 hover:bg-gray-700 hover:text-red-300'
                            : 'text-red-600 hover:bg-gray-100 hover:text-red-700'
                        }`}
                        title="Delete"
                      >
                        <Trash2 className="h-4 w-4" />
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
        <div
          className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
        >
          Showing {filteredUsers.length} of{' '}
          {users.filter((u) => !u.is_service_account).length} user(s)
        </div>
      )}
    </div>
  )
}
