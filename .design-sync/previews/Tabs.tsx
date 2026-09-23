import { Tabs, TabsContent, TabsList, TabsTrigger } from 'imbi-ui'
import { Stethoscope } from 'lucide-react'

const PANEL = 'text-secondary text-sm'

export const ProjectTabs = () => (
  <Tabs className="w-full max-w-2xl" defaultValue="overview">
    <TabsList className="mb-6">
      <TabsTrigger value="overview">Overview</TabsTrigger>
      <TabsTrigger value="deployments">Deployments</TabsTrigger>
      <TabsTrigger value="releases">Releases</TabsTrigger>
      <TabsTrigger value="operations">Operations Log</TabsTrigger>
      <TabsTrigger aria-label="Project Doctor" className="ml-auto" value="doctor">
        <Stethoscope className="size-4" />
      </TabsTrigger>
    </TabsList>
    <TabsContent className={PANEL} value="overview">
      imbi-api is the core HTTP API for the Imbi platform, owned by Platform
      Engineering.
    </TabsContent>
    <TabsContent className={PANEL} value="deployments">
      production is running 2.35.1; staging is running 2.36.0-rc.1.
    </TabsContent>
    <TabsContent className={PANEL} value="releases">
      2.36.0-rc.1 is waiting for promotion to production.
    </TabsContent>
    <TabsContent className={PANEL} value="operations">
      Rolled back 2.34.2 in production after elevated 5xx rates.
    </TabsContent>
    <TabsContent className={PANEL} value="doctor">
      2 checks failing: missing SonarQube key, stale README.
    </TabsContent>
  </Tabs>
)

export const SecondTabActive = () => (
  <Tabs className="w-full max-w-2xl" defaultValue="deployments">
    <TabsList className="mb-6">
      <TabsTrigger value="overview">Overview</TabsTrigger>
      <TabsTrigger value="deployments">Deployments</TabsTrigger>
      <TabsTrigger value="releases">Releases</TabsTrigger>
    </TabsList>
    <TabsContent className={PANEL} value="overview">
      imbi-api is the core HTTP API for the Imbi platform, owned by Platform
      Engineering.
    </TabsContent>
    <TabsContent className={PANEL} value="deployments">
      production is running 2.35.1; staging is running 2.36.0-rc.1.
    </TabsContent>
    <TabsContent className={PANEL} value="releases">
      2.36.0-rc.1 is waiting for promotion to production.
    </TabsContent>
  </Tabs>
)

export const WithDisabledTab = () => (
  <Tabs className="w-full max-w-2xl" defaultValue="general">
    <TabsList className="mb-6">
      <TabsTrigger value="general">General</TabsTrigger>
      <TabsTrigger value="notifications">Notifications</TabsTrigger>
      <TabsTrigger value="api-keys">API Keys</TabsTrigger>
      <TabsTrigger disabled value="sso">
        SSO
      </TabsTrigger>
    </TabsList>
    <TabsContent className={PANEL} value="general">
      Display name, email address, and theme preferences.
    </TabsContent>
    <TabsContent className={PANEL} value="notifications">
      Email and Slack alerts for deployments and score changes.
    </TabsContent>
    <TabsContent className={PANEL} value="api-keys">
      Personal API keys for the Imbi CLI and MCP clients.
    </TabsContent>
  </Tabs>
)
