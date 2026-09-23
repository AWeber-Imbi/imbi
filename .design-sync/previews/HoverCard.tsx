import {
  EnvironmentBadge,
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from 'imbi-ui'
import { CircleCheck, Info } from 'lucide-react'

export const EnvironmentRelease = () => (
  <div className="flex justify-center p-6">
    <HoverCard defaultOpen openDelay={150}>
      <HoverCardTrigger asChild>
        <span>
          <EnvironmentBadge
            label_color="#ef4444"
            name="Production"
            slug="production"
          />
        </span>
      </HoverCardTrigger>
      <HoverCardContent align="center" className="w-55 overflow-hidden p-0">
        <div className="p-3">
          <p className="text-secondary mb-1.5 flex items-center gap-1.5 text-sm font-medium">
            <span
              className="size-2 shrink-0 rounded-full"
              style={{ backgroundColor: '#ef4444' }}
            />
            Production
          </p>
          <p className="flex items-center gap-2 font-mono text-base leading-tight font-bold">
            2.35.1
            <CircleCheck className="text-success size-4 shrink-0" />
          </p>
          <p className="text-tertiary mt-1 text-xs">
            Deployed 3 hours ago by gavinr
          </p>
        </div>
      </HoverCardContent>
    </HoverCard>
  </div>
)

export const AttributeDescription = () => (
  <div className="flex justify-center p-6">
    <HoverCard defaultOpen>
      <HoverCardTrigger asChild>
        <span className="inline-flex cursor-help items-center gap-1 text-sm text-muted-foreground">
          SLO target
          <Info className="size-3.5" />
        </span>
      </HoverCardTrigger>
      <HoverCardContent className="w-80 text-sm" side="bottom">
        Monthly availability objective for the service. Error budget alerts
        fire when the rolling 30-day availability drops below this value.
      </HoverCardContent>
    </HoverCard>
  </div>
)
