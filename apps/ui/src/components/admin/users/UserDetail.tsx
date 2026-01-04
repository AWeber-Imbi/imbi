import { ArrowLeft, Edit2, Power, Clock, User, Mail, Calendar, Shield, Users } from 'lucide-react'
import { Button } from '../../ui/button'
import { Gravatar } from '../../ui/gravatar'
import type { AdminUser } from '@/types'

interface UserDetailProps {
  user: AdminUser
  onEdit: () => void
  onBack: () => void
  isDarkMode: boolean
}

export function UserDetail({ user, onEdit, onBack, isDarkMode }: UserDetailProps) {
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

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="outline" onClick={onBack} className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}>
            <ArrowLeft className="w-4 h-4 mr-2" />
            Back
          </Button>
          <div className="flex items-center gap-3">
            <Gravatar
              email={user.email}
              size={48}
              alt={user.display_name}
              className="w-12 h-12 rounded-full"
            />
            <div>
              <h2 className={`text-2xl ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
                {user.display_name}
              </h2>
              <p className={`mt-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                {user.email}
              </p>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={onEdit} className="bg-[#2A4DD0] hover:bg-blue-700 text-white">
            <Edit2 className="w-4 h-4 mr-2" />
            Edit User
          </Button>
        </div>
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
            user.is_active
              ? isDarkMode ? 'bg-green-900/30 text-green-400' : 'bg-green-100 text-green-700'
              : isDarkMode ? 'bg-gray-700 text-gray-400' : 'bg-gray-100 text-gray-600'
          }`}>
            <Power className="w-4 h-4" />
            {user.is_active ? 'Active' : 'Inactive'}
          </div>
          {user.is_admin && (
            <div className={`flex items-center gap-2 px-3 py-1.5 rounded ${
              isDarkMode ? 'bg-red-900/30 text-red-400' : 'bg-red-100 text-red-700'
            }`}>
              <Shield className="w-4 h-4" />
              Administrator
            </div>
          )}
          {user.is_service_account && (
            <div className={`flex items-center gap-2 px-3 py-1.5 rounded ${
              isDarkMode ? 'bg-purple-900/30 text-purple-400' : 'bg-purple-100 text-purple-700'
            }`}>
              Service Account
            </div>
          )}
        </div>
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
              {user.email}
            </div>
          </div>

          <div>
            <div className={`flex items-center gap-2 text-sm mb-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
              <User className="w-4 h-4" />
              Display Name
            </div>
            <div className={isDarkMode ? 'text-white' : 'text-gray-900'}>
              {user.display_name}
            </div>
          </div>

          <div>
            <div className={`flex items-center gap-2 text-sm mb-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
              <Calendar className="w-4 h-4" />
              Created
            </div>
            <div className={isDarkMode ? 'text-white' : 'text-gray-900'}>
              {formatDate(user.created_at)}
            </div>
          </div>

          <div>
            <div className={`flex items-center gap-2 text-sm mb-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
              <Clock className="w-4 h-4" />
              Last Login
            </div>
            <div className={isDarkMode ? 'text-white' : 'text-gray-900'}>
              {formatDate(user.last_login)}
            </div>
          </div>
        </div>
      </div>

      {/* Groups & Roles */}
      <div className={`p-6 rounded-lg border ${
        isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
      }`}>
        <h3 className={`mb-4 font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
          Groups & Roles
        </h3>

        <div className="grid grid-cols-2 gap-6">
          <div>
            <div className={`flex items-center gap-2 text-sm mb-2 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
              <Users className="w-4 h-4" />
              Group Membership
            </div>
            {user.groups.length > 0 ? (
              <div className="space-y-1">
                {user.groups.map((group) => (
                  <div key={group.slug} className={`text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                    • {group.name}
                    {group.description && (
                      <span className={`text-xs ml-2 ${isDarkMode ? 'text-gray-500' : 'text-gray-500'}`}>
                        ({group.description})
                      </span>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className={`text-sm ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}>
                No groups
              </div>
            )}
          </div>

          <div>
            <div className={`flex items-center gap-2 text-sm mb-2 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
              <Shield className="w-4 h-4" />
              Direct Roles
            </div>
            {user.roles.length > 0 ? (
              <div className="space-y-1">
                {user.roles.map((role) => (
                  <div key={role.slug} className={`text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                    • {role.name}
                    {role.description && (
                      <span className={`text-xs ml-2 ${isDarkMode ? 'text-gray-500' : 'text-gray-500'}`}>
                        ({role.description})
                      </span>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className={`text-sm ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}>
                No direct roles
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Active Sessions */}
      <div className={`p-6 rounded-lg border ${
        isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
      }`}>
        <h3 className={`mb-4 font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
          Active Sessions
        </h3>
        <div className={`text-center py-8 ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
          <div>0 active sessions</div>
          <div className="text-sm mt-1">No JWT tokens currently active for this user</div>
        </div>
      </div>
    </div>
  )
}
