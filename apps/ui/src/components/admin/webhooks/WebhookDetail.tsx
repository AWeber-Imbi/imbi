import { ArrowLeft, Edit2, Webhook } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { EntityIcon } from '@/components/ui/entity-icon'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { Webhook as WebhookType } from '@/types'

interface WebhookDetailProps {
  onBack: () => void
  onEdit: () => void
  webhook: WebhookType
}

export function WebhookDetail({ onBack, onEdit, webhook }: WebhookDetailProps) {
  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button onClick={onBack} variant="outline">
            <ArrowLeft className="mr-2 size-4" />
            Back
          </Button>
          <div>
            <div className="flex items-center gap-3">
              {webhook.icon ? (
                <EntityIcon
                  className="size-8 rounded object-cover"
                  icon={webhook.icon}
                />
              ) : (
                <div className="flex size-8 items-center justify-center rounded-lg bg-indigo-50 dark:bg-indigo-900/30">
                  <Webhook className="size-5 text-indigo-600 dark:text-indigo-400" />
                </div>
              )}
              <CardTitle>{webhook.name}</CardTitle>
            </div>
            {webhook.description && (
              <p className="text-secondary mt-1 text-sm">
                {webhook.description}
              </p>
            )}
          </div>
        </div>
        <Button
          className="bg-action text-action-foreground hover:bg-action-hover"
          onClick={onEdit}
        >
          <Edit2 className="mr-2 size-4" />
          Edit Webhook
        </Button>
      </div>

      {/* Webhook Info */}
      <Card>
        <CardHeader className="pb-4">
          <CardTitle>Configuration</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-6">
            <div>
              <div className="text-secondary text-sm">ID</div>
              <div className="mt-1">
                <code className="bg-secondary text-primary rounded px-2 py-1 text-sm">
                  {webhook.id}
                </code>
              </div>
            </div>
            <div>
              <div className="text-secondary text-sm">Notification Path</div>
              <div className="mt-1">
                <code className="bg-secondary text-primary rounded px-2 py-1 text-sm">
                  {webhook.notification_path}
                </code>
              </div>
            </div>
            <div>
              <div className="text-secondary text-sm">Slug</div>
              <div className="mt-1">
                <code className="bg-secondary text-primary rounded px-2 py-1 text-sm">
                  {webhook.slug}
                </code>
              </div>
            </div>
            <div>
              <div className="text-secondary text-sm">Third-Party Service</div>
              <div className="text-primary mt-1">
                {(webhook.third_party_service?.name as string | undefined) || (
                  <span className="text-tertiary">None</span>
                )}
              </div>
            </div>
            {webhook.identifier_selector && (
              <div>
                <div className="text-secondary text-sm">
                  Identifier Selector
                </div>
                <div className="mt-1">
                  <code className="bg-secondary text-primary rounded px-2 py-1 text-sm">
                    {webhook.identifier_selector}
                  </code>
                </div>
              </div>
            )}
            {webhook.user_subject_selector && (
              <div>
                <div className="text-secondary text-sm">
                  User Subject Selector
                </div>
                <div className="mt-1">
                  <code className="bg-secondary text-primary rounded px-2 py-1 text-sm">
                    {webhook.user_subject_selector}
                  </code>
                </div>
              </div>
            )}
            {webhook.identity_plugin_slug && (
              <div>
                <div className="text-secondary text-sm">
                  Identity Plugin Slug
                </div>
                <div className="mt-1">
                  <code className="bg-secondary text-primary rounded px-2 py-1 text-sm">
                    {webhook.identity_plugin_slug}
                  </code>
                </div>
              </div>
            )}
            {webhook.event_type_selector && (
              <div>
                <div className="text-secondary text-sm">
                  Event Type Selector
                </div>
                <div className="mt-1">
                  <code className="bg-secondary text-primary rounded px-2 py-1 text-sm">
                    {webhook.event_type_selector}
                  </code>
                </div>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Rules */}
      <Card>
        <CardHeader className="pb-4">
          <CardTitle>Rules ({webhook.rules.length})</CardTitle>
        </CardHeader>
        <CardContent>
          {webhook.rules.length === 0 ? (
            <div className="text-tertiary py-6 text-center text-sm">
              No rules defined for this webhook.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader className="border-tertiary border-b">
                  <TableRow>
                    <TableHead className="text-tertiary w-12 px-4 py-2 text-left text-xs tracking-wider uppercase">
                      #
                    </TableHead>
                    <TableHead className="text-tertiary px-4 py-2 text-left text-xs tracking-wider uppercase">
                      Filter Expression
                    </TableHead>
                    <TableHead className="text-tertiary px-4 py-2 text-left text-xs tracking-wider uppercase">
                      Handler
                    </TableHead>
                    <TableHead className="text-tertiary px-4 py-2 text-left text-xs tracking-wider uppercase">
                      Config
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody className="divide-tertiary divide-y">
                  {webhook.rules.map((rule, index) => (
                    <TableRow key={index}>
                      <TableCell className="text-tertiary px-4 py-3 text-sm">
                        {index + 1}
                      </TableCell>
                      <TableCell className="px-4 py-3">
                        <code className="bg-secondary text-primary rounded px-2 py-1 text-sm">
                          {rule.filter_expression}
                        </code>
                      </TableCell>
                      <TableCell className="px-4 py-3">
                        <code className="bg-secondary text-primary rounded px-2 py-1 text-sm">
                          {rule.handler}
                        </code>
                      </TableCell>
                      <TableCell className="px-4 py-3">
                        {rule.handler_config &&
                        (Array.isArray(rule.handler_config)
                          ? rule.handler_config.length > 0
                          : Object.keys(rule.handler_config).length > 0) ? (
                          <code className="bg-secondary text-primary rounded px-2 py-1 text-sm">
                            {JSON.stringify(rule.handler_config)}
                          </code>
                        ) : (
                          <span className="text-tertiary">--</span>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
