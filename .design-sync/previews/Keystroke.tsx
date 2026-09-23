import { Input, Keystroke } from 'imbi-ui'

export const Shortcuts = () => (
  <div className="flex flex-col gap-3 text-sm">
    <div className="flex w-64 items-center justify-between">
      <span className="text-secondary">Open command bar</span>
      <Keystroke isMac value="Ctrl+K" />
    </div>
    <div className="flex w-64 items-center justify-between">
      <span className="text-secondary">Search projects</span>
      <Keystroke isMac value="/" />
    </div>
    <div className="flex w-64 items-center justify-between">
      <span className="text-secondary">New project</span>
      <Keystroke isMac value="Ctrl+Shift+N" />
    </div>
    <div className="flex w-64 items-center justify-between">
      <span className="text-secondary">Next result</span>
      <Keystroke isMac value="ArrowDown" />
    </div>
  </div>
)

export const MacVsOther = () => (
  <div className="flex flex-col gap-3 text-sm">
    <div className="flex w-80 items-center justify-between">
      <span className="text-secondary">macOS</span>
      <Keystroke isMac value="Ctrl+Alt+Shift+P" />
    </div>
    <div className="flex w-80 items-center justify-between">
      <span className="text-secondary">Windows / Linux</span>
      <Keystroke isMac={false} value="Ctrl+Alt+Shift+P" />
    </div>
  </div>
)

export const InSearchInput = () => (
  <div className="relative w-80">
    <Input aria-label="Search projects" placeholder="Search projects…" />
    <div className="pointer-events-none absolute top-1/2 right-2.5 -translate-y-1/2">
      <Keystroke value="/" />
    </div>
  </div>
)
