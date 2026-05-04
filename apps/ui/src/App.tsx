import { lazy, Suspense, useEffect } from 'react'

import { Navigate, Route, Routes } from 'react-router-dom'

import { Toaster } from 'sonner'

import { BootstrapGate } from './components/BootstrapGate'
import { ErrorBoundary } from './components/ErrorBoundary'
import { OrganizationProvider } from './contexts/OrganizationContext'
import { ThemeProvider } from './contexts/ThemeContext'
import { useAuth } from './hooks/useAuth'

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
const AdminPage = lazy(() =>
  import('./pages/AdminPage').then((m) => ({ default: m.AdminPage })),
)
const ReportsPage = lazy(() =>
  import('./pages/ReportsPage').then((m) => ({ default: m.ReportsPage })),
)
const SettingsPage = lazy(() =>
  import('./pages/SettingsPage').then((m) => ({ default: m.SettingsPage })),
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
                      <ReportsPage />
                    </ProtectedRoute>
                  }
                  path="/reports"
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

function PageFallback() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="text-lg">Loading…</div>
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
