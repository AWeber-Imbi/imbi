import React from 'react'

import { BrowserRouter } from 'react-router-dom'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ReactDOM from 'react-dom/client'

import App from './App.tsx'
import './index.css'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 5 * 60 * 1000, // 5 minutes
    },
  },
})

// Cache the root on the container so Vite HMR re-evaluating this module
// doesn't call createRoot() twice on the same node, which produces a
// React warning and a cascade of removeChild errors during dev reloads.
const container = document.getElementById('root')!
type ContainerWithRoot = HTMLElement & { __reactRoot?: ReactDOM.Root }
const node = container as ContainerWithRoot
const root = node.__reactRoot ?? ReactDOM.createRoot(node)
node.__reactRoot = root

root.render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
)
