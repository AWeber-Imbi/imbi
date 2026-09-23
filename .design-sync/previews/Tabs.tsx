import { Tabs, TabsContent, TabsList, TabsTrigger } from 'imbi-ui'
import { Stethoscope } from 'lucide-react'

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
    <TabsContent className="text-secondary text-sm" value="overview">
      imbi-api is the core HTTP API for the Imbi platform, owned by Platform
      Engineering.
    </TabsContent>
    <TabsContent value="deployments">Deployments</TabsContent>
  </Tabs>
)

export const SecondTabActive = () => (
  <Tabs className="w-full max-w-2xl" defaultValue="deployments">
    <TabsList className="mb-6">
      <TabsTrigger value="overview">Overview</TabsTrigger>
      <TabsTrigger value="deployments">Deployments</TabsTrigger>
      <TabsTrigger value="releases">Releases</TabsTrigger>
    </TabsList>
    <TabsContent className="text-secondary text-sm" value="deployments">
      production is running 2.35.1; staging is running 2.36.0-rc.1.
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
    <TabsContent className="text-secondary text-sm" value="general">
      Display name, email address, and theme preferences.
    </TabsContent>
  </Tabs>
)
