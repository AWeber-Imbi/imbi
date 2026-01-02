import { useState } from 'react'
import { Plus, Search, Filter, Edit2, Trash2, Eye, Power, Crown, Bot } from 'lucide-react'
import { Button } from '../ui/button'
import { Input } from '../ui/input'

interface UserManagementProps {
  isDarkMode: boolean
}

interface User {
  id: string
  username: string
  email: string
  display_name: string
  avatar_url?: string
  is_active: boolean
  is_admin: boolean
  is_service_account: boolean
  created_at: string
  last_login?: string
  groups: string[]
  roles: string[]
}

type UserFilter = 'all' | 'users' | 'service' | 'admins'
type StatusFilter = 'all' | 'active' | 'inactive'

// Mock data
const mockUsers: User[] = [
  {
    id: '1',
    username: 'admin',
    email: 'admin@imbi.local',
    display_name: 'Administrator',
    is_active: true,
    is_admin: true,
    is_service_account: false,
    created_at: '2024-01-01T00:00:00Z',
    last_login: '2024-12-30T14:30:00Z',
    groups: [],
    roles: []
  },
  {
    id: '2',
    username: 'alice.johnson',
    email: 'alice.johnson@aweber.com',
    display_name: 'Alice Johnson',
    avatar_url: 'https://i.pravatar.cc/150?u=alice',
    is_active: true,
    is_admin: false,
    is_service_account: false,
    created_at: '2024-02-15T10:00:00Z',
    last_login: '2024-12-31T09:15:00Z',
    groups: ['backend-team', 'engineering'],
    roles: ['developer', 'team-lead']
  },
  {
    id: '3',
    username: 'bob.smith',
    email: 'bob.smith@aweber.com',
    display_name: 'Bob Smith',
    avatar_url: 'https://i.pravatar.cc/150?u=bob',
    is_active: true,
    is_admin: false,
    is_service_account: false,
    created_at: '2024-03-10T08:00:00Z',
    last_login: '2024-12-29T16:45:00Z',
    groups: ['frontend-team', 'engineering'],
    roles: ['developer']
  },
  {
    id: '4',
    username: 'imbi-automations',
    email: 'automations@imbi.local',
    display_name: 'Imbi Automation Service',
    is_active: true,
    is_admin: false,
    is_service_account: true,
    created_at: '2024-01-05T00:00:00Z',
    last_login: '2024-12-31T10:00:00Z',
    groups: [],
    roles: ['service-account']
  },
  {
    id: '5',
    username: 'contractor.jane',
    email: 'jane@contractor.com',
    display_name: 'Jane Contractor',
    is_active: false,
    is_admin: false,
    is_service_account: false,
    created_at: '2024-06-01T00:00:00Z',
    last_login: '2024-09-30T17:00:00Z',
    groups: ['contractors'],
    roles: ['read-only']
  }
]

export function UserManagement({ isDarkMode }: UserManagementProps) {
  const [users, setUsers] = useState<User[]>(mockUsers)
  const [searchQuery, setSearchQuery] = useState('')
  const [userFilter, setUserFilter] = useState<UserFilter>('all')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())

  // Filter users
  const filteredUsers = users.filter(user => {
    // Search filter
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      const matches =
        user.username.toLowerCase().includes(query) ||
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

  const handleToggleActive = (id: string) => {
    setUsers(users.map(user =>
      user.id === id ? { ...user, is_active: !user.is_active } : user
    ))
  }

  const handleDelete = (id: string) => {
    if (confirm('Are you sure you want to delete this user? This action cannot be undone.')) {
      setUsers(users.filter(user => user.id !== id))
    }
  }

  const handleBulkActivate = (activate: boolean) => {
    setUsers(users.map(user =>
      selectedIds.has(user.id) ? { ...user, is_active: activate } : user
    ))
    setSelectedIds(new Set())
  }

  const handleBulkDelete = () => {
    if (confirm(`Are you sure you want to delete ${selectedIds.size} user(s)? This action cannot be undone.`)) {
      setUsers(users.filter(user => !selectedIds.has(user.id)))
      setSelectedIds(new Set())
    }
  }

  const toggleSelection = (id: string) => {
    const newSelection = new Set(selectedIds)
    if (newSelection.has(id)) {
      newSelection.delete(id)
    } else {
      newSelection.add(id)
    }
    setSelectedIds(newSelection)
  }

  const toggleSelectAll = () => {
    if (selectedIds.size === filteredUsers.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(filteredUsers.map(u => u.id)))
    }
  }

  const formatDate = (dateString?: string) => {
    if (!dateString) return 'Never'
    return new Date(dateString).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
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
              placeholder="Search by username, email, or name..."
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
      {selectedIds.size > 0 && (
        <div className={`flex items-center justify-between p-4 rounded-lg border ${
          isDarkMode ? 'bg-blue-900/20 border-blue-700' : 'bg-blue-50 border-blue-200'
        }`}>
          <span className={`text-sm ${isDarkMode ? 'text-blue-300' : 'text-blue-900'}`}>
            {selectedIds.size} user(s) selected
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
                  checked={selectedIds.size === filteredUsers.length && filteredUsers.length > 0}
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
                  key={user.id}
                  className={`${isDarkMode ? 'hover:bg-gray-750' : 'hover:bg-gray-50'} ${
                    !user.is_active ? 'opacity-60' : ''
                  }`}
                >
                  <td className="px-4 py-3">
                    <input
                      type="checkbox"
                      checked={selectedIds.has(user.id)}
                      onChange={() => toggleSelection(user.id)}
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
                          @{user.username}
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
                      onClick={() => handleToggleActive(user.id)}
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
                        onClick={() => handleDelete(user.id)}
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
