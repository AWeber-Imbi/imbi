import {
  Button,
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from 'imbi-ui'
import {
  Activity,
  ChevronDown,
  FilePlus2,
  FolderKanban,
  Plus,
  Rocket,
  Settings,
  Trash2,
} from 'lucide-react'

export const ProjectActions = () => (
  <div className="flex justify-center p-6">
    <DropdownMenu defaultOpen modal={false}>
      <DropdownMenuTrigger asChild>
        <Button className="gap-2" size="sm" variant="outline">
          Actions
          <ChevronDown className="size-3" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-56">
        <DropdownMenuLabel>imbi-api</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem>
          <Rocket className="mr-2 size-4" />
          <span>Deploy to staging</span>
        </DropdownMenuItem>
        <DropdownMenuItem>
          <Activity className="mr-2 size-4" />
          <span>New Ops Log Entry</span>
          <DropdownMenuShortcut>⌘L</DropdownMenuShortcut>
        </DropdownMenuItem>
        <DropdownMenuItem>
          <Settings className="mr-2 size-4" />
          <span>Settings</span>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem className="text-danger">
          <Trash2 className="mr-2 size-4" />
          <span>Delete project</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  </div>
)

export const QuickCreate = () => (
  <div className="flex justify-center p-6">
    <DropdownMenu defaultOpen modal={false}>
      <DropdownMenuTrigger asChild>
        <Button className="gap-2" size="sm" variant="outline">
          <Plus className="size-4" />
          <ChevronDown className="size-3" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-56">
        <DropdownMenuItem>
          <Activity className="mr-2 size-4" />
          <span>New Ops Log Entry</span>
        </DropdownMenuItem>
        <DropdownMenuItem>
          <FolderKanban className="mr-2 size-4" />
          <span>New Project</span>
        </DropdownMenuItem>
        <DropdownMenuItem>
          <FilePlus2 className="mr-2 size-4" />
          <span>New Document</span>
        </DropdownMenuItem>
        <DropdownMenuItem disabled>
          <Rocket className="mr-2 size-4" />
          <span>New Release</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  </div>
)

export const EnvironmentFilter = () => (
  <div className="flex justify-center p-6">
    <DropdownMenu defaultOpen modal={false}>
      <DropdownMenuTrigger asChild>
        <Button className="gap-2" size="sm" variant="outline">
          Environments
          <ChevronDown className="size-3" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-48">
        <DropdownMenuLabel>Show environments</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuCheckboxItem checked>Production</DropdownMenuCheckboxItem>
        <DropdownMenuCheckboxItem checked>Staging</DropdownMenuCheckboxItem>
        <DropdownMenuCheckboxItem checked={false}>
          Testing
        </DropdownMenuCheckboxItem>
      </DropdownMenuContent>
    </DropdownMenu>
  </div>
)
