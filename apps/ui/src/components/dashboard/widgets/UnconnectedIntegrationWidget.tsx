import { useEffect } from 'react'

import { Lock, Plug } from 'lucide-react'

import logoDark from '@/assets/logo-dark.svg'
import logoLight from '@/assets/logo-light.svg'
import { Button } from '@/components/ui/button'
import { useTheme } from '@/contexts/ThemeContext'
import { getIcon, iconRegistry, useIconRegistryVersion } from '@/lib/icons'
import type { IconComponent } from '@/lib/icons'
import type { InstalledPlugin } from '@/types'

interface UnconnectedIntegrationWidgetProps {
  onConnect: () => void
  onManage: () => void
  pending: boolean
  plugin: InstalledPlugin
}

// Dashboard "sales pitch" tile rendered for an enabled identity plugin
// the actor hasn't yet connected.  The widget can't be removed from the
// dashboard — it disappears on its own once the connection is active.
export function UnconnectedIntegrationWidget({
  onConnect,
  onManage,
  pending,
  plugin,
}: UnconnectedIntegrationWidgetProps) {
  const { isDarkMode } = useTheme()
  const version = useIconRegistryVersion()
  const iconValue = plugin.icon ?? null

  useEffect(() => {
    if (iconValue) void iconRegistry.loadSetFor(iconValue)
  }, [iconValue])

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const ResolvedIcon: IconComponent | null = iconValue
    ? getIcon(iconValue, null)
    : null
  void version

  const body =
    plugin.widget_text ||
    plugin.description ||
    `Imbi can act on your behalf in ${plugin.name} once you link your account.`

  return (
    <article className="relative grid min-h-[240px] grid-cols-1 overflow-hidden rounded-2xl border border-border bg-card shadow-sm md:grid-cols-[1fr_160px] xl:grid-cols-[1fr_200px]">
      <div className="flex flex-col justify-between p-6">
        <div>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-border bg-amber-bg px-2.5 py-0.5 text-[11px] font-semibold tracking-wide text-amber-text">
            <span className="relative inline-block h-1.5 w-1.5 rounded-full bg-amber-border">
              <span className="absolute -inset-[3px] rounded-full border-[1.5px] border-amber-border [animation:imbi-pulse-ring_2s_ease-out_infinite]" />
            </span>
            {plugin.name} · Not connected
          </span>

          <h3 className="mb-1 mt-3.5 text-[17px] font-semibold tracking-tight text-primary">
            {plugin.name} isn&apos;t linked to your account
          </h3>

          <p className="m-0 max-w-[38ch] text-[13px] leading-relaxed text-secondary">
            {body}
          </p>

          <div
            aria-label="Preview of locked content"
            className="relative mt-3.5 rounded-[10px] border border-dashed border-tertiary bg-tertiary p-2.5"
          >
            <div className="flex items-center gap-2 py-1.5">
              <span className="h-1.5 flex-[0.4] rounded-[3px] bg-gradient-to-r from-[var(--color-text-tertiary)] to-secondary [filter:blur(1.5px)]" />
              <span className="h-1.5 flex-1 rounded-[3px] bg-gradient-to-r from-[var(--color-text-tertiary)] to-secondary [filter:blur(1.5px)]" />
            </div>
            <div className="flex items-center gap-2 border-t border-border py-1.5">
              <span className="h-1.5 flex-[0.7] rounded-[3px] bg-gradient-to-r from-[var(--color-text-tertiary)] to-secondary [filter:blur(1.5px)]" />
              <span className="h-1.5 flex-[0.4] rounded-[3px] bg-gradient-to-r from-[var(--color-text-tertiary)] to-secondary [filter:blur(1.5px)]" />
            </div>
            <div className="flex items-center gap-2 border-t border-border py-1.5">
              <span className="h-1.5 flex-1 rounded-[3px] bg-gradient-to-r from-[var(--color-text-tertiary)] to-secondary [filter:blur(1.5px)]" />
              <span className="h-1.5 flex-[0.7] rounded-[3px] bg-gradient-to-r from-[var(--color-text-tertiary)] to-secondary [filter:blur(1.5px)]" />
            </div>
            <div className="absolute left-1/2 top-1/2 grid h-7 w-7 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border border-border bg-card text-secondary shadow-sm">
              <Lock className="h-3.5 w-3.5" strokeWidth={1.8} />
            </div>
          </div>
        </div>

        <div className="mt-[18px] flex items-center gap-2.5">
          <Button
            className="h-auto gap-2 rounded-[9px] px-3.5 py-2 text-[13px] font-medium"
            disabled={pending}
            onClick={onConnect}
          >
            {ResolvedIcon ? (
              <ResolvedIcon className="h-3.5 w-3.5" />
            ) : (
              <Plug className="h-3.5 w-3.5" />
            )}
            Connect {plugin.name}
          </Button>
          <button
            className="inline-flex items-center gap-1 text-xs font-medium text-secondary hover:text-primary"
            onClick={onManage}
            type="button"
          >
            Manage in settings →
          </button>
        </div>
      </div>

      <div
        aria-hidden="true"
        className="from-tertiary relative hidden overflow-hidden border-l border-border bg-gradient-to-b to-secondary md:block"
      >
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="flex items-center gap-1.5">
            <div className="grid h-[46px] w-[46px] place-items-center rounded-xl border border-border bg-card shadow-sm">
              <img
                alt="Imbi"
                className="h-7 w-7"
                src={isDarkMode ? logoDark : logoLight}
              />
            </div>
            <div className="flex gap-[5px]">
              <i className="block h-[5px] w-[5px] rounded-full bg-[var(--color-text-tertiary)] [animation:imbi-bridge-travel_1.6s_ease-in-out_infinite]" />
              <i className="block h-[5px] w-[5px] rounded-full bg-[var(--color-text-tertiary)] [animation-delay:0.15s] [animation:imbi-bridge-travel_1.6s_ease-in-out_infinite]" />
              <i className="block h-[5px] w-[5px] rounded-full bg-[var(--color-text-tertiary)] [animation-delay:0.3s] [animation:imbi-bridge-travel_1.6s_ease-in-out_infinite]" />
              <i className="block h-[5px] w-[5px] rounded-full bg-[var(--color-text-tertiary)] [animation-delay:0.45s] [animation:imbi-bridge-travel_1.6s_ease-in-out_infinite]" />
            </div>
            <div className="grid h-[46px] w-[46px] place-items-center rounded-xl border border-border bg-card text-primary opacity-50 shadow-sm grayscale-[0.4]">
              {ResolvedIcon ? (
                <ResolvedIcon className="h-[22px] w-[22px]" />
              ) : (
                <Plug className="h-[22px] w-[22px]" />
              )}
            </div>
          </div>
        </div>
        <div className="pointer-events-none absolute -bottom-3 -right-3 select-none font-mono text-[84px] font-semibold leading-none tracking-[-0.04em] text-amber-border opacity-[0.06]">
          {'{ }'}
        </div>
      </div>
    </article>
  )
}
