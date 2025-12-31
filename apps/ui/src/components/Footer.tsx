import { ExternalLink } from 'lucide-react'

export function Footer() {
  return (
    <footer className="border-t border-slate-200 bg-white">
      <div className="max-w-[1400px] mx-auto px-6 py-3 flex items-center justify-between">
        <div className="text-slate-600 text-sm">
          Imbi 2.0.0
        </div>
        <div className="flex items-center gap-4">
          <a
            href="https://imbi.readthedocs.io"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 text-slate-600 hover:text-slate-900 transition-colors text-sm"
          >
            <ExternalLink className="w-4 h-4" />
            Documentation
          </a>
          <a
            href="https://github.com/aweber/imbi"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 text-slate-600 hover:text-slate-900 transition-colors text-sm"
          >
            <ExternalLink className="w-4 h-4" />
            GitHub
          </a>
        </div>
      </div>
    </footer>
  )
}
