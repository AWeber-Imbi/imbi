import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
} from 'imbi-ui'

export const RenameProject = () => (
  <Dialog open>
    <DialogContent>
      <DialogHeader>
        <DialogTitle>Rename project</DialogTitle>
        <DialogDescription>
          The slug updates too. Existing links to the old slug redirect.
        </DialogDescription>
      </DialogHeader>
      <div className="grid gap-2 p-6">
        <Label htmlFor="project-name">Project name</Label>
        <Input defaultValue="imbi-api" id="project-name" />
      </div>
      <DialogFooter>
        <Button variant="outline">Cancel</Button>
        <Button>Save</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
)
