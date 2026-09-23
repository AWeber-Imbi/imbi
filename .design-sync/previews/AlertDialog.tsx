import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  EnvironmentBadge,
  buttonVariants,
} from 'imbi-ui'

export const DeleteProject = () => (
  <AlertDialog open>
    <AlertDialogContent className="sm:max-w-md">
      <AlertDialogHeader>
        <AlertDialogTitle>Delete imbi-api?</AlertDialogTitle>
        <AlertDialogDescription>
          This removes the project, its environments, and its deployment
          history. This action cannot be undone.
        </AlertDialogDescription>
      </AlertDialogHeader>
      <AlertDialogFooter>
        <AlertDialogCancel>Cancel</AlertDialogCancel>
        <AlertDialogAction
          className={buttonVariants({ variant: 'destructive' })}
        >
          Delete project
        </AlertDialogAction>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>
)

export const PromoteRelease = () => (
  <AlertDialog open>
    <AlertDialogContent className="sm:max-w-md">
      <AlertDialogHeader>
        <AlertDialogTitle>Promote 2.35.1 to production?</AlertDialogTitle>
        <AlertDialogDescription>
          imbi-api will deploy the release currently running in staging.
        </AlertDialogDescription>
      </AlertDialogHeader>
      <div className="flex items-center gap-2 rounded-md border p-3 text-sm">
        <EnvironmentBadge label_color="#f59e0b" name="Staging" slug="staging" />
        <span className="text-tertiary">to</span>
        <EnvironmentBadge
          label_color="#ef4444"
          name="Production"
          slug="production"
        />
        <span className="ml-auto font-mono text-xs">6141081e</span>
      </div>
      <AlertDialogFooter>
        <AlertDialogCancel>Cancel</AlertDialogCancel>
        <AlertDialogAction>Promote</AlertDialogAction>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>
)
