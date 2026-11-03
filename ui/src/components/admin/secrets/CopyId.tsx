import { Copy } from 'lucide-react'
import { toast } from 'sonner'

/** A row id, shortened, that copies the full id to the clipboard. */
export function CopyId({ id }: { id: string }) {
  return (
    <button
      aria-label={`Copy id ${id}`}
      className="text-secondary hover:text-primary flex items-center gap-1 font-mono text-xs"
      onClick={() =>
        void navigator.clipboard
          ?.writeText(id)
          .then(() => toast.success('Id copied'))
      }
      title={id}
      type="button"
    >
      {id.slice(0, 8)}
      <Copy className="size-3" />
    </button>
  )
}
