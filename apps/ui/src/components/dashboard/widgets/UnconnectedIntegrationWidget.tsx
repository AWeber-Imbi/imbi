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
    <article className="border-border bg-card relative grid min-h-60 grid-cols-1 overflow-hidden rounded-2xl border shadow-sm md:grid-cols-[1fr_160px] xl:grid-cols-[1fr_200px]">
      <div className="flex flex-col justify-between p-6">
        <div>
          <span className="border-amber-border bg-amber-bg text-amber-text inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold tracking-wide">
            <span className="bg-amber-border relative inline-block size-1.5 rounded-full">
              <span className="border-amber-border absolute -inset-0.75 animate-[imbi-pulse-ring_2s_ease-out_infinite] rounded-full border-[1.5px]" />
            </span>
            {plugin.name} · Not connected
          </span>

          <h3 className="text-primary mt-3.5 mb-1 text-[17px] font-semibold tracking-tight">
            {plugin.name} isn&apos;t linked to your account
          </h3>

          <p className="text-secondary m-0 max-w-[38ch] text-[13px] leading-relaxed">
            {body}
          </p>

          <div
            aria-label="Preview of locked content"
            className="border-tertiary bg-tertiary relative mt-3.5 rounded-[10px] border border-dashed p-2.5"
          >
            <div className="flex items-center gap-2 py-1.5">
              <span className="to-secondary h-1.5 flex-[0.4] rounded-[3px] bg-linear-to-r from-(--text-color-tertiary) filter-[blur(1.5px)]" />
              <span className="to-secondary h-1.5 flex-1 rounded-[3px] bg-linear-to-r from-(--text-color-tertiary) filter-[blur(1.5px)]" />
            </div>
            <div className="border-border flex items-center gap-2 border-t py-1.5">
              <span className="to-secondary h-1.5 flex-[0.7] rounded-[3px] bg-linear-to-r from-(--text-color-tertiary) filter-[blur(1.5px)]" />
              <span className="to-secondary h-1.5 flex-[0.4] rounded-[3px] bg-linear-to-r from-(--text-color-tertiary) filter-[blur(1.5px)]" />
            </div>
            <div className="border-border flex items-center gap-2 border-t py-1.5">
              <span className="to-secondary h-1.5 flex-1 rounded-[3px] bg-linear-to-r from-(--text-color-tertiary) filter-[blur(1.5px)]" />
              <span className="to-secondary h-1.5 flex-[0.7] rounded-[3px] bg-linear-to-r from-(--text-color-tertiary) filter-[blur(1.5px)]" />
            </div>
            <div className="border-border bg-card text-secondary absolute top-1/2 left-1/2 grid size-7 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border shadow-sm">
              <Lock className="size-3.5" strokeWidth={1.8} />
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
              <ResolvedIcon className="size-3.5" />
            ) : (
              <Plug className="size-3.5" />
            )}
            Connect {plugin.name}
          </Button>
          <button
            className="text-secondary hover:text-primary inline-flex items-center gap-1 text-xs font-medium"
            onClick={onManage}
            type="button"
          >
            Manage in settings →
          </button>
        </div>
      </div>

      <div
        aria-hidden="true"
        className="border-border from-tertiary to-secondary relative hidden overflow-hidden border-l bg-linear-to-b md:block"
      >
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="flex items-center gap-1.5">
            <div className="border-border bg-card grid size-11.5 place-items-center rounded-xl border shadow-sm">
              <img
                alt="Imbi"
                className="size-7"
                src={isDarkMode ? logoDark : logoLight}
              />
            </div>
            <div className="flex gap-1.25">
              <i className="block size-1.25 animate-[imbi-bridge-travel_1.6s_ease-in-out_infinite] rounded-full bg-(--text-color-tertiary)" />
              <i className="block size-1.25 animate-[imbi-bridge-travel_1.6s_ease-in-out_infinite] rounded-full bg-(--text-color-tertiary) [animation-delay:0.15s]" />
              <i className="block size-1.25 animate-[imbi-bridge-travel_1.6s_ease-in-out_infinite] rounded-full bg-(--text-color-tertiary) [animation-delay:0.3s]" />
              <i className="block size-1.25 animate-[imbi-bridge-travel_1.6s_ease-in-out_infinite] rounded-full bg-(--text-color-tertiary) [animation-delay:0.45s]" />
            </div>
            <div className="border-border bg-card text-primary grid size-11.5 place-items-center rounded-xl border opacity-50 shadow-sm grayscale-[0.4]">
              {ResolvedIcon ? (
                <ResolvedIcon className="size-[22px]" />
              ) : (
                <Plug className="size-[22px]" />
              )}
            </div>
          </div>
        </div>
        <div className="text-amber-border pointer-events-none absolute -right-3 -bottom-3 font-mono text-[84px] leading-none font-semibold tracking-[-0.04em] opacity-[0.06] select-none">
          {'{ }'}
        </div>
      </div>
    </article>
  )
}
