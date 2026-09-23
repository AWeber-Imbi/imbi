import { Card, CardContent, Sk, Skeleton, SkText, Swap } from 'imbi-ui'

export const SkPrimitives = () => (
  <div className="flex w-80 flex-col gap-4">
    <div className="flex items-center gap-3">
      <Sk circle h={32} w={32} />
      <div className="flex flex-1 flex-col gap-2">
        <Sk line w="60%" />
        <Sk line w="35%" />
      </div>
    </div>
    <Sk h={16} w="45%" />
    <Sk h={28} r={6} w={104} />
    <SkText />
  </div>
)

export const DriftCard = () => (
  <div className="border-tertiary flex w-96 flex-col gap-3 rounded-lg border p-4">
    <div className="flex items-center justify-between gap-3">
      <Sk h={16} w="30%" />
      <Sk h={28} r={6} w={104} />
    </div>
    <SkText widths={['100%', '70%']} />
  </div>
)

export const AssistantContent = () => (
  <div className="border-tertiary flex w-96 flex-col gap-3 rounded-lg border p-4">
    <div className="text-secondary text-sm font-medium">
      Imbi Assistant is writing a summary…
    </div>
    <SkText ai widths={['100%', '94%', '88%', '52%']} />
  </div>
)

export const SwapLoadingAndReady = () => (
  <div className="flex w-96 flex-col gap-3">
    <Swap
      className="border-tertiary rounded-lg border p-4"
      ready={false}
      skeleton={<SkText widths={['40%', '85%']} />}
    >
      <div />
    </Swap>
    <Swap className="border-tertiary rounded-lg border p-4" ready skeleton={null}>
      <div className="text-primary text-sm font-medium">imbi-api 2.35.1</div>
      <div className="text-secondary text-sm">
        Released to production 12 minutes ago.
      </div>
    </Swap>
  </div>
)

export const LegacySkeleton = () => (
  <Card className="w-80">
    <CardContent className="flex flex-col gap-3 pt-6">
      <Skeleton className="h-4 w-40" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-3/4" />
    </CardContent>
  </Card>
)
