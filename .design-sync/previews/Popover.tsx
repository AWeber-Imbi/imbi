import {
  Button,
  Checkbox,
  Input,
  Label,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from 'imbi-ui'
import { Filter, Link2 } from 'lucide-react'

export const ActivityFilter = () => (
  <div className="flex justify-center p-6">
    <Popover defaultOpen>
      <PopoverTrigger asChild>
        <Button size="sm" variant="outline">
          <Filter className="size-3.5" />
          Filter
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-44 p-2">
        <p className="text-tertiary px-1 pb-1.5 text-[11px] font-semibold tracking-wider uppercase">
          Show
        </p>
        <label className="hover:bg-secondary flex cursor-pointer items-center gap-2 rounded-sm px-1 py-1.5 text-sm">
          <Checkbox defaultChecked />
          People
        </label>
        <label className="hover:bg-secondary flex cursor-pointer items-center gap-2 rounded-sm px-1 py-1.5 text-sm">
          <Checkbox />
          Bots
        </label>
      </PopoverContent>
    </Popover>
  </div>
)

export const AddLink = () => (
  <div className="flex justify-center p-6">
    <Popover defaultOpen>
      <PopoverTrigger asChild>
        <Button size="sm" variant="outline">
          <Link2 className="size-4" />
          Add link
        </Button>
      </PopoverTrigger>
      <PopoverContent
        className="w-80"
        onOpenAutoFocus={(event) => event.preventDefault()}
      >
        <div className="grid gap-4">
          <div className="space-y-1">
            <h4 className="text-sm font-medium">Project link</h4>
            <p className="text-sm text-muted-foreground">
              Shown on the imbi-api overview page.
            </p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="link-label">Label</Label>
            <Input defaultValue="Runbook" id="link-label" />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="link-url">URL</Label>
            <Input
              defaultValue="https://wiki.example.com/imbi-api/runbook"
              id="link-url"
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="outline">
              Cancel
            </Button>
            <Button size="sm">Save</Button>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  </div>
)
