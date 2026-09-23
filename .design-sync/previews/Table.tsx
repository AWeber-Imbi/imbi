import {
  Badge,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from 'imbi-ui'

const deployments = [
  {
    env: 'production',
    project: 'imbi-api',
    status: 'success',
    version: '2.35.1',
    when: '12 minutes ago',
  },
  {
    env: 'staging',
    project: 'imbi-api',
    status: 'info',
    version: '2.36.0-rc.1',
    when: '1 hour ago',
  },
  {
    env: 'production',
    project: 'imbi-gateway',
    status: 'success',
    version: '1.8.4',
    when: '3 hours ago',
  },
  {
    env: 'staging',
    project: 'imbi-assistant',
    status: 'danger',
    version: '0.9.2',
    when: 'yesterday',
  },
  {
    env: 'production',
    project: 'imbi-scheduler',
    status: 'success',
    version: '2.35.0',
    when: '2 days ago',
  },
] as const

const statusLabel = { danger: 'Failed', info: 'Deploying', success: 'Live' }

export const Deployments = () => (
  <div className="w-full max-w-3xl">
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Project</TableHead>
          <TableHead>Environment</TableHead>
          <TableHead>Version</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="text-right">Deployed</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {deployments.map((d) => (
          <TableRow key={`${d.project}-${d.env}`}>
            <TableCell className="font-medium">{d.project}</TableCell>
            <TableCell className="text-secondary">{d.env}</TableCell>
            <TableCell className="font-mono text-xs">{d.version}</TableCell>
            <TableCell>
              <Badge variant={d.status}>{statusLabel[d.status]}</Badge>
            </TableCell>
            <TableCell className="text-tertiary text-right">{d.when}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  </div>
)

export const WithCaptionAndFooter = () => (
  <div className="w-full max-w-xl">
    <Table>
      <TableCaption>Open incidents per team, last 30 days.</TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>Team</TableHead>
          <TableHead className="text-right">Projects</TableHead>
          <TableHead className="text-right">Incidents</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        <TableRow>
          <TableCell>Platform Engineering</TableCell>
          <TableCell className="text-right">24</TableCell>
          <TableCell className="text-right">3</TableCell>
        </TableRow>
        <TableRow>
          <TableCell>Data Services</TableCell>
          <TableCell className="text-right">17</TableCell>
          <TableCell className="text-right">1</TableCell>
        </TableRow>
        <TableRow>
          <TableCell>Messaging</TableCell>
          <TableCell className="text-right">9</TableCell>
          <TableCell className="text-right">0</TableCell>
        </TableRow>
      </TableBody>
      <TableFooter>
        <TableRow>
          <TableCell>Total</TableCell>
          <TableCell className="text-right">50</TableCell>
          <TableCell className="text-right">4</TableCell>
        </TableRow>
      </TableFooter>
    </Table>
  </div>
)

export const SelectedRow = () => (
  <div className="w-full max-w-xl">
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Environment</TableHead>
          <TableHead>Region</TableHead>
          <TableHead className="text-right">Projects</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        <TableRow>
          <TableCell>development</TableCell>
          <TableCell className="text-secondary">us-east-1</TableCell>
          <TableCell className="text-right">41</TableCell>
        </TableRow>
        <TableRow data-state="selected">
          <TableCell className="font-medium">staging</TableCell>
          <TableCell className="text-secondary">us-east-1</TableCell>
          <TableCell className="text-right">38</TableCell>
        </TableRow>
        <TableRow>
          <TableCell>production</TableCell>
          <TableCell className="text-secondary">us-east-1, us-west-2</TableCell>
          <TableCell className="text-right">36</TableCell>
        </TableRow>
      </TableBody>
    </Table>
  </div>
)
