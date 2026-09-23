import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from 'imbi-ui'

export const Default = () => (
  <Card className="w-96">
    <CardHeader>
      <CardTitle>Deployments</CardTitle>
      <CardDescription>Recent releases across environments</CardDescription>
    </CardHeader>
    <CardContent className="text-secondary text-sm">
      3 deployments in the last 24 hours.
    </CardContent>
    <CardFooter className="justify-end">
      <Button size="sm" variant="outline">
        View all
      </Button>
    </CardFooter>
  </Card>
)

export const HeaderAndContent = () => (
  <Card className="w-96">
    <CardHeader>
      <CardTitle>imbi-api</CardTitle>
      <CardDescription>Platform Engineering · HTTP API</CardDescription>
    </CardHeader>
    <CardContent>
      <div className="flex flex-col gap-2 text-sm">
        <div className="flex items-center justify-between">
          <span className="text-secondary">production</span>
          <Badge variant="success">2.35.1</Badge>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-secondary">staging</span>
          <Badge variant="info">2.36.0-rc.1</Badge>
        </div>
      </div>
    </CardContent>
  </Card>
)

export const ContentOnly = () => (
  <Card className="w-96">
    <CardContent className="pt-6 text-sm text-muted-foreground">
      No deployments recorded for imbi-gateway yet.
    </CardContent>
  </Card>
)
