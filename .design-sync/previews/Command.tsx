import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut,
} from 'imbi-ui'
import { Activity, Check, FolderKanban, Rocket, Settings } from 'lucide-react'

export const ProjectSearch = () => (
  <Command
    className="w-96 rounded-lg border shadow-md"
    label="Search projects and actions"
  >
    <CommandInput placeholder="Search projects and actions..." />
    <CommandList>
      <CommandEmpty>No results found.</CommandEmpty>
      <CommandGroup heading="Projects">
        <CommandItem>
          <FolderKanban />
          imbi-api
        </CommandItem>
        <CommandItem>
          <FolderKanban />
          imbi-gateway
        </CommandItem>
        <CommandItem>
          <FolderKanban />
          imbi-scheduler
        </CommandItem>
      </CommandGroup>
      <CommandSeparator />
      <CommandGroup heading="Actions">
        <CommandItem>
          <Activity />
          New Ops Log Entry
          <CommandShortcut>⌘L</CommandShortcut>
        </CommandItem>
        <CommandItem>
          <Rocket />
          Deploy to staging
        </CommandItem>
        <CommandItem>
          <Settings />
          Settings
          <CommandShortcut>⌘,</CommandShortcut>
        </CommandItem>
      </CommandGroup>
    </CommandList>
  </Command>
)

const teams = ['Platform', 'Data Engineering', 'Messaging', 'Web']

export const TeamPicker = () => (
  <Command className="w-64 rounded-md border shadow-md" label="Pick a team">
    <CommandInput placeholder="Search..." />
    <CommandList>
      <CommandEmpty>No results found.</CommandEmpty>
      <CommandGroup>
        {teams.map((team) => (
          <CommandItem key={team} value={team}>
            <Check
              className={team === 'Platform' ? 'opacity-100' : 'opacity-0'}
            />
            {team}
          </CommandItem>
        ))}
      </CommandGroup>
    </CommandList>
  </Command>
)

export const NoResults = () => (
  <Command className="w-64 rounded-md border shadow-md" label="Pick a team">
    <CommandInput
      onValueChange={() => {}}
      placeholder="Search..."
      value="kafka-bridge"
    />
    <CommandList>
      <CommandEmpty>No results found.</CommandEmpty>
      <CommandGroup>
        <CommandItem>Platform</CommandItem>
        <CommandItem>Messaging</CommandItem>
      </CommandGroup>
    </CommandList>
  </Command>
)
