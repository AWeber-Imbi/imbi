import { ArrowLeft, Edit2, Webhook } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { Webhook as WebhookType } from '@/types'

interface WebhookDetailProps {
  webhook: WebhookType
  onEdit: () => void
  onBack: () => void
  isDarkMode: boolean
}

export function WebhookDetail({
  webhook,
  onEdit,
  onBack,
  isDarkMode,
}: WebhookDetailProps) {
  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button
            variant="outline"
            onClick={onBack}
            className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}
          >
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back
          </Button>
          <div>
            <div className="flex items-center gap-3">
              {webhook.icon ? (
                <img
                  src={webhook.icon}
                  alt=""
                  className="h-8 w-8 rounded object-cover"
                />
              ) : (
                <div
                  className={`flex h-8 w-8 items-center justify-center rounded-lg ${
                    isDarkMode ? 'bg-indigo-900/30' : 'bg-indigo-50'
                  }`}
                >
                  <Webhook
                    className={`h-5 w-5 ${isDarkMode ? 'text-indigo-400' : 'text-indigo-600'}`}
                  />
                </div>
              )}
              <h2
                className={`text-2xl font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
              >
                {webhook.name}
              </h2>
            </div>
            {webhook.description && (
              <p
                className={`mt-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              >
                {webhook.description}
              </p>
            )}
          </div>
        </div>
        <Button
          onClick={onEdit}
          className="bg-[#2A4DD0] text-white hover:bg-blue-700"
        >
          <Edit2 className="mr-2 h-4 w-4" />
          Edit Webhook
        </Button>
      </div>

      {/* Webhook Info */}
      <div
        className={`rounded-lg border p-6 ${
          isDarkMode
            ? 'border-gray-700 bg-gray-800'
            : 'border-gray-200 bg-white'
        }`}
      >
        <h3
          className={`text-lg mb-4 font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
        >
          Configuration
        </h3>
        <div className="grid grid-cols-2 gap-6">
          <div>
            <div
              className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
            >
              Slug
            </div>
            <div className="mt-1">
              <code
                className={`rounded px-2 py-1 text-sm ${
                  isDarkMode
                    ? 'bg-gray-700 text-gray-300'
                    : 'bg-gray-100 text-gray-700'
                }`}
              >
                {webhook.slug}
              </code>
            </div>
          </div>
          <div>
            <div
              className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
            >
              Notification Path
            </div>
            <div className="mt-1">
              <code
                className={`rounded px-2 py-1 text-sm ${
                  isDarkMode
                    ? 'bg-gray-700 text-gray-300'
                    : 'bg-gray-100 text-gray-700'
                }`}
              >
                {webhook.notification_path}
              </code>
            </div>
          </div>
          <div>
            <div
              className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
            >
              Third-Party Service
            </div>
            <div
              className={`mt-1 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
            >
              {webhook.third_party_service?.name || (
                <span
                  className={isDarkMode ? 'text-gray-500' : 'text-gray-400'}
                >
                  None
                </span>
              )}
            </div>
          </div>
          {webhook.identifier_selector && (
            <div>
              <div
                className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              >
                Identifier Selector
              </div>
              <div className="mt-1">
                <code
                  className={`rounded px-2 py-1 text-sm ${
                    isDarkMode
                      ? 'bg-gray-700 text-gray-300'
                      : 'bg-gray-100 text-gray-700'
                  }`}
                >
                  {webhook.identifier_selector}
                </code>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Rules */}
      <div
        className={`rounded-lg border p-6 ${
          isDarkMode
            ? 'border-gray-700 bg-gray-800'
            : 'border-gray-200 bg-white'
        }`}
      >
        <h3
          className={`text-lg mb-4 font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
        >
          Rules ({webhook.rules.length})
        </h3>

        {webhook.rules.length === 0 ? (
          <div
            className={`py-6 text-center text-sm ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
          >
            No rules defined for this webhook.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead
                className={`border-b ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
              >
                <tr>
                  <th
                    className={`w-12 px-4 py-2 text-left text-xs uppercase tracking-wider ${
                      isDarkMode ? 'text-gray-400' : 'text-gray-500'
                    }`}
                  >
                    #
                  </th>
                  <th
                    className={`px-4 py-2 text-left text-xs uppercase tracking-wider ${
                      isDarkMode ? 'text-gray-400' : 'text-gray-500'
                    }`}
                  >
                    Filter Expression
                  </th>
                  <th
                    className={`px-4 py-2 text-left text-xs uppercase tracking-wider ${
                      isDarkMode ? 'text-gray-400' : 'text-gray-500'
                    }`}
                  >
                    Handler
                  </th>
                  <th
                    className={`px-4 py-2 text-left text-xs uppercase tracking-wider ${
                      isDarkMode ? 'text-gray-400' : 'text-gray-500'
                    }`}
                  >
                    Config
                  </th>
                </tr>
              </thead>
              <tbody
                className={`divide-y ${isDarkMode ? 'divide-gray-700' : 'divide-gray-200'}`}
              >
                {webhook.rules.map((rule, index) => (
                  <tr key={index}>
                    <td
                      className={`px-4 py-3 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
                    >
                      {index + 1}
                    </td>
                    <td className="px-4 py-3">
                      <code
                        className={`rounded px-2 py-1 text-sm ${
                          isDarkMode
                            ? 'bg-gray-700 text-gray-300'
                            : 'bg-gray-100 text-gray-700'
                        }`}
                      >
                        {rule.filter_expression}
                      </code>
                    </td>
                    <td className="px-4 py-3">
                      <code
                        className={`rounded px-2 py-1 text-sm ${
                          isDarkMode
                            ? 'bg-gray-700 text-gray-300'
                            : 'bg-gray-100 text-gray-700'
                        }`}
                      >
                        {rule.handler}
                      </code>
                    </td>
                    <td className="px-4 py-3">
                      {rule.handler_config &&
                      (Array.isArray(rule.handler_config)
                        ? rule.handler_config.length > 0
                        : Object.keys(rule.handler_config).length > 0) ? (
                        <code
                          className={`rounded px-2 py-1 text-sm ${
                            isDarkMode
                              ? 'bg-gray-700 text-gray-300'
                              : 'bg-gray-100 text-gray-700'
                          }`}
                        >
                          {JSON.stringify(rule.handler_config)}
                        </code>
                      ) : (
                        <span
                          className={
                            isDarkMode ? 'text-gray-500' : 'text-gray-400'
                          }
                        >
                          --
                        </span>
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
