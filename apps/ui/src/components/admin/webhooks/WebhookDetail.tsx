import { ArrowLeft, Edit2, Webhook } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { Webhook as WebhookType } from '@/types'

interface WebhookDetailProps {
  webhook: WebhookType
  onEdit: () => void
  onBack: () => void
  isDarkMode: boolean
}

export function WebhookDetail({ webhook, onEdit, onBack, isDarkMode }: WebhookDetailProps) {
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
            <div className="flex items-center gap-3">
              {webhook.icon ? (
                <img src={webhook.icon} alt="" className="w-8 h-8 rounded object-cover" />
              ) : (
                <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                  isDarkMode ? 'bg-indigo-900/30' : 'bg-indigo-50'
                }`}>
                  <Webhook className={`w-5 h-5 ${isDarkMode ? 'text-indigo-400' : 'text-indigo-600'}`} />
                </div>
              )}
              <h2 className={`text-2xl font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
                {webhook.name}
              </h2>
            </div>
            {webhook.description && (
              <p className={`mt-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                {webhook.description}
              </p>
            )}
          </div>
        </div>
        <Button onClick={onEdit} className="bg-[#2A4DD0] hover:bg-blue-700 text-white">
          <Edit2 className="w-4 h-4 mr-2" />
          Edit Webhook
        </Button>
      </div>

      {/* Webhook Info */}
      <div className={`p-6 rounded-lg border ${
        isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
      }`}>
        <h3 className={`text-lg font-semibold mb-4 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
          Configuration
        </h3>
        <div className="grid grid-cols-2 gap-6">
          <div>
            <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>Slug</div>
            <div className="mt-1">
              <code className={`px-2 py-1 rounded text-sm ${
                isDarkMode ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-700'
              }`}>
                {webhook.slug}
              </code>
            </div>
          </div>
          <div>
            <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>Notification Path</div>
            <div className="mt-1">
              <code className={`px-2 py-1 rounded text-sm ${
                isDarkMode ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-700'
              }`}>
                {webhook.notification_path}
              </code>
            </div>
          </div>
          <div>
            <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>Third-Party Service</div>
            <div className={`mt-1 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
              {webhook.third_party_service?.name || (
                <span className={isDarkMode ? 'text-gray-500' : 'text-gray-400'}>None</span>
              )}
            </div>
          </div>
          {webhook.identifier_selector && (
            <div>
              <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>Identifier Selector</div>
              <div className="mt-1">
                <code className={`px-2 py-1 rounded text-sm ${
                  isDarkMode ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-700'
                }`}>
                  {webhook.identifier_selector}
                </code>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Rules */}
      <div className={`p-6 rounded-lg border ${
        isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
      }`}>
        <h3 className={`text-lg font-semibold mb-4 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
          Rules ({webhook.rules.length})
        </h3>

        {webhook.rules.length === 0 ? (
          <div className={`text-center py-6 text-sm ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}>
            No rules defined for this webhook.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className={`border-b ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}>
                <tr>
                  <th className={`px-4 py-2 text-left text-xs uppercase tracking-wider w-12 ${
                    isDarkMode ? 'text-gray-400' : 'text-gray-500'
                  }`}>#</th>
                  <th className={`px-4 py-2 text-left text-xs uppercase tracking-wider ${
                    isDarkMode ? 'text-gray-400' : 'text-gray-500'
                  }`}>Filter Expression</th>
                  <th className={`px-4 py-2 text-left text-xs uppercase tracking-wider ${
                    isDarkMode ? 'text-gray-400' : 'text-gray-500'
                  }`}>Handler</th>
                  <th className={`px-4 py-2 text-left text-xs uppercase tracking-wider ${
                    isDarkMode ? 'text-gray-400' : 'text-gray-500'
                  }`}>Config</th>
                </tr>
              </thead>
              <tbody className={`divide-y ${isDarkMode ? 'divide-gray-700' : 'divide-gray-200'}`}>
                {webhook.rules.map((rule, index) => (
                  <tr key={index}>
                    <td className={`px-4 py-3 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
                      {index + 1}
                    </td>
                    <td className="px-4 py-3">
                      <code className={`px-2 py-1 rounded text-sm ${
                        isDarkMode ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-700'
                      }`}>
                        {rule.filter_expression}
                      </code>
                    </td>
                    <td className="px-4 py-3">
                      <code className={`px-2 py-1 rounded text-sm ${
                        isDarkMode ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-700'
                      }`}>
                        {rule.handler}
                      </code>
                    </td>
                    <td className="px-4 py-3">
                      {rule.handler_config && (Array.isArray(rule.handler_config) ? rule.handler_config.length > 0 : Object.keys(rule.handler_config).length > 0) ? (
                        <code className={`px-2 py-1 rounded text-sm ${
                          isDarkMode ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-700'
                        }`}>
                          {JSON.stringify(rule.handler_config)}
                        </code>
                      ) : (
                        <span className={isDarkMode ? 'text-gray-500' : 'text-gray-400'}>--</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
