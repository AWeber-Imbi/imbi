import { lazy, Suspense, useEffect } from 'react'

import { Navigate, Route, Routes } from 'react-router-dom'

import { Toaster } from 'sonner'

import { BootstrapGate } from './components/BootstrapGate'
import { ErrorBoundary } from './components/ErrorBoundary'
import { Sk } from './components/ui/skeleton'
import { OrganizationProvider } from './contexts/OrganizationContext'
import { ThemeProvider } from './contexts/ThemeContext'
import { useAuth } from './hooks/useAuth'
import { useVersionCheck } from './hooks/useVersionCheck'

const DashboardPage = lazy(() =>
  import('./pages/DashboardPage').then((m) => ({ default: m.DashboardPage })),
)
const ProjectsPage = lazy(() =>
  import('./pages/ProjectsPage').then((m) => ({ default: m.ProjectsPage })),
)
const ProjectDetailPage = lazy(() =>
  import('./pages/ProjectDetailPage').then((m) => ({
    default: m.ProjectDetailPage,
  })),
)
const OperationsLogPage = lazy(() =>
  import('./pages/OperationsLogPage').then((m) => ({
    default: m.OperationsLogPage,
  })),
)
const DocumentsIndexPage = lazy(() =>
  import('./pages/DocumentsIndexPage').then((m) => ({
    default: m.DocumentsIndexPage,
  })),
)
const AdminPage = lazy(() =>
  import('./pages/AdminPage').then((m) => ({ default: m.AdminPage })),
)
const ReportsPage = lazy(() =>
  import('./pages/ReportsPage').then((m) => ({ default: m.ReportsPage })),
)
const SettingsPage = lazy(() =>
  import('./pages/SettingsPage').then((m) => ({ default: m.SettingsPage })),
)
const UserProfilePage = lazy(() =>
  import('./pages/UserProfile/UserProfilePage').then((m) => ({
    default: m.UserProfilePage,
  })),
)
const LoginPage = lazy(() =>
  import('./pages/LoginPage').then((m) => ({ default: m.LoginPage })),
)
const OAuthCallbackPage = lazy(() =>
  import('./pages/OAuthCallbackPage').then((m) => ({
    default: m.OAuthCallbackPage,
  })),
)

function AdminProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading, user } = useAuth()

  useEffect(() => {
    if (!isAuthenticated && !isLoading) savePostLoginRedirect()
  }, [isAuthenticated, isLoading])

  if (isLoading) {
    return <PageFallback />
  }

  if (!isAuthenticated) {
    return <Navigate replace to="/login" />
  }

  const isAdmin = user?.is_admin === true
  if (!isAdmin) {
    return <Navigate replace to="/dashboard" />
  }

  return <>{children}</>
}

function App() {
  useVersionCheck()
  return (
    <ThemeProvider>
      <Toaster position="top-right" richColors />
      <OrganizationProvider>
        <ErrorBoundary>
          <Suspense fallback={<PageFallback />}>
            <BootstrapGate fallback={<PageFallback />}>
              <Routes>
                <Route element={<LoginPage />} path="/login" />
                <Route element={<OAuthCallbackPage />} path="/auth/callback" />

                <Route
                  element={
                    <ProtectedRoute>
                      <DashboardPage />
                    </ProtectedRoute>
                  }
                  path="/dashboard"
                />
                <Route
                  element={
                    <ProtectedRoute>
                      <ProjectsPage />
                    </ProtectedRoute>
                  }
                  path="/projects"
                />
                <Route
                  element={
                    <ProtectedRoute>
                      <ProjectDetailPage />
                    </ProtectedRoute>
                  }
                  path="/projects/:projectId/:tab?/:subId?/:subAction?"
                />
                <Route
                  element={
                    <ProtectedRoute>
                      <OperationsLogPage />
                    </ProtectedRoute>
                  }
                  path="/operations-log"
                />
                <Route
                  element={
                    <ProtectedRoute>
                      <DocumentsIndexPage />
                    </ProtectedRoute>
                  }
                  path="/documents/:subId?/:subAction?"
                />
                <Route
                  element={
                    <ProtectedRoute>
                      <ReportsPage />
                    </ProtectedRoute>
                  }
                  path="/reports/:reportId?"
                />
                <Route
                  element={
                    <ProtectedRoute>
                      <SettingsPage />
                    </ProtectedRoute>
                  }
                  path="/settings/:tab?"
                />
                <Route
                  element={
                    <AdminProtectedRoute>
                      <AdminPage />
                    </AdminProtectedRoute>
                  }
                  path="/admin/:section?/:slug?/:action?"
                />
                <Route
                  element={
                    <ProtectedRoute>
                      <UserProfilePage />
                    </ProtectedRoute>
                  }
                  path="/users/:email/:tab?/:subId?/:subAction?"
                />
                <Route
                  element={<Navigate replace to="/operations-log" />}
                  path="/opslog"
                />
                <Route
                  element={<Navigate replace to="/dashboard" />}
                  path="/"
                />
                <Route
                  element={<Navigate replace to="/dashboard" />}
                  path="*"
                />
              </Routes>
            </BootstrapGate>
          </Suspense>
        </ErrorBoundary>
      </OrganizationProvider>
    </ThemeProvider>
  )
}

// App-shell skeleton shown while a lazy route chunk loads, during the
// bootstrap gate, and during auth resolution. Mirrors the fixed top nav
// (<Navigation />) plus a generic content footprint so the chrome reads as
// present before the page module arrives — never a centered "Loading…".
function PageFallback() {
  return (
    <div aria-busy className="bg-tertiary text-primary min-h-screen">
      <div className="border-tertiary bg-primary fixed top-0 right-0 left-0 z-50 border-b">
        <div className="flex h-16 items-center justify-between px-6">
          <div className="flex items-center gap-8">
            <div className="flex items-center gap-2">
              <Sk circle h={32} w={32} />
              <Sk h={14} r={4} w={64} />
            </div>
            <div className="hidden items-center gap-6 md:flex">
              {[56, 64, 72, 60].map((w, i) => (
                <Sk h={14} key={i} r={4} w={w} />
              ))}
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Sk h={32} r={8} w={140} />
            <Sk circle h={32} w={32} />
          </div>
        </div>
      </div>
      <main className="mx-auto max-w-[1400px] px-6 pt-24">
        <Sk h={28} r={6} w={220} />
        <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Sk h={96} key={i} r={12} />
          ))}
        </div>
        <div className="mt-6 space-y-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Sk h={56} key={i} r={8} />
          ))}
        </div>
      </main>
    </div>
  )
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth()

  useEffect(() => {
    if (!isAuthenticated && !isLoading) savePostLoginRedirect()
  }, [isAuthenticated, isLoading])

  if (isLoading) {
    return <PageFallback />
  }

  if (!isAuthenticated) {
    return <Navigate replace to="/login" />
  }

  return <>{children}</>
}

function savePostLoginRedirect() {
  const { pathname, search } = window.location
  if (pathname === '/login' || pathname === '/auth/callback') return
  sessionStorage.setItem('imbi_redirect_after_login', pathname + search)
}

export default App
