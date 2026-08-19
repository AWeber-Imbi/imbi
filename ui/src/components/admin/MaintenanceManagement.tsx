import { useNavigate, useParams } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'

import { getMaintenanceOperations } from '@/api/endpoints'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

import { MaintenanceActivityLog } from './MaintenanceActivityLog'
import { MaintenanceOperations } from './MaintenanceOperations'

// The Maintenance admin page. Operations is the live view — what is
// running now, from Valkey. Activity is the durable history from
// ClickHouse, which outlives the run state by months; keeping them on
// separate tabs is what stops two failure lists reading as a
// contradiction.
export function MaintenanceManagement() {
  // The tab lives in the URL so a reload — or a shared link — comes back
  // to the tab you were on: /admin/maintenance is Operations,
  // /admin/maintenance/activity is Activity.
  const navigate = useNavigate()
  const { slug } = useParams<{ slug?: string }>()
  const tab = slug === 'activity' ? 'activity' : 'operations'
  // The registry, for the Activity tab's operation filter. Deliberately
  // not `useMaintenanceOperations`: that hook toasts every run's terminal
  // transition, and a second instance would toast each one twice. This
  // shares its cache entry and adds nothing.
  const { data: operations } = useQuery({
    queryFn: ({ signal }) => getMaintenanceOperations(signal),
    queryKey: ['maintenance-operations'],
  })

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-primary text-2xl font-semibold tracking-tight">
          Maintenance
        </h1>
      </div>

      <Tabs
        onValueChange={(value) =>
          navigate(
            value === 'activity'
              ? '/admin/maintenance/activity'
              : '/admin/maintenance',
          )
        }
        value={tab}
      >
        <TabsList className="mb-6">
          <TabsTrigger value="operations">Operations</TabsTrigger>
          <TabsTrigger value="activity">Activity</TabsTrigger>
        </TabsList>
        <TabsContent value="operations">
          <MaintenanceOperations />
        </TabsContent>
        <TabsContent value="activity">
          <MaintenanceActivityLog operations={operations ?? []} />
        </TabsContent>
      </Tabs>
    </div>
  )
}
