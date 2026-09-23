// App-level context that some ui/ primitives read: react-query (API-backed
// pickers), react-router (links), and the theme. Mirrors ui/src/main.tsx and
// ui/src/App.tsx without the auth and network setup.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { type ReactNode, useState } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { Toaster } from 'sonner'

import { ThemeProvider } from '@/contexts/ThemeContext'

/** Wraps an Imbi UI tree with the providers the app root supplies. */
export function ImbiProvider({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: false, staleTime: Infinity } },
      }),
  )
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ThemeProvider>
          <Toaster position="top-right" richColors />
          {children}
        </ThemeProvider>
      </MemoryRouter>
    </QueryClientProvider>
  )
}
