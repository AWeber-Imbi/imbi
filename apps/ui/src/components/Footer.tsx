import { ExternalLink } from 'lucide-react'

interface FooterProps {
  isDarkMode?: boolean
}

export function Footer({ isDarkMode = false }: FooterProps) {
  return (
    <footer className={`border-t transition-colors ${
      isDarkMode
        ? 'border-gray-700 bg-gray-800'
        : 'border-slate-200 bg-white'
    }`}>
      <div className="max-w-[1400px] mx-auto px-6 py-3 flex items-center justify-between">
        <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-slate-600'}`}>
          Imbi 2.0.0
        </div>
        <div className="flex items-center gap-4">
          <a
            href="https://imbi.readthedocs.io"
            target="_blank"
            rel="noopener noreferrer"
            className={`flex items-center gap-2 transition-colors text-sm ${
              isDarkMode
                ? 'text-gray-400 hover:text-white'
                : 'text-slate-600 hover:text-slate-900'
            }`}
          >
            <ExternalLink className="w-4 h-4" />
            Documentation
          </a>
          <a
            href="https://github.com/aweber/imbi"
            target="_blank"
            rel="noopener noreferrer"
            className={`flex items-center gap-2 transition-colors text-sm ${
              isDarkMode
                ? 'text-gray-400 hover:text-white'
                : 'text-slate-600 hover:text-slate-900'
            }`}
          >
            <ExternalLink className="w-4 h-4" />
            GitHub
          </a>
        </div>
      </div>
    </footer>
  )
}
