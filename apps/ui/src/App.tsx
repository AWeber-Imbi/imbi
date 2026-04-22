import { lazy, Suspense, useEffect } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { Toaster } from 'sonner'
import { BootstrapGate } from './components/BootstrapGate'
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

function PageFallback() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="text-lg">Loading…</div>
    </div>
  )
}

function savePostLoginRedirect() {
  const { pathname, search } = window.location
  if (pathname === '/login' || pathname === '/auth/callback') return
  sessionStorage.setItem('imbi_redirect_after_login', pathname + search)
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
    return <Navigate to="/login" replace />
  }

  return <>{children}</>
}

function AdminProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading, user } = useAuth()

  useEffect(() => {
    if (!isAuthenticated && !isLoading) savePostLoginRedirect()
  }, [isAuthenticated, isLoading])

  if (isLoading) {
    return <PageFallback />
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  const isAdmin = user?.is_admin === true
  if (!isAdmin) {
    return <Navigate to="/dashboard" replace />
  }

  return <>{children}</>
}

function App() {
  return (
    <ThemeProvider>
      <Toaster richColors position="top-right" />
      <OrganizationProvider>
        <Suspense fallback={<PageFallback />}>
          <BootstrapGate fallback={<PageFallback />}>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/auth/callback" element={<OAuthCallbackPage />} />

              <Route
                path="/dashboard"
                element={
                  <ProtectedRoute>
                    <DashboardPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/projects"
                element={
                  <ProtectedRoute>
                    <ProjectsPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/projects/:projectId/:tab?"
                element={
                  <ProtectedRoute>
                    <ProjectDetailPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/operations-log"
                element={
                  <ProtectedRoute>
                    <OperationsLogPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/settings/:tab?"
                element={
                  <ProtectedRoute>
                    <SettingsPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/admin/:section?/:slug?/:action?"
                element={
                  <AdminProtectedRoute>
                    <AdminPage />
                  </AdminProtectedRoute>
                }
              />
              <Route
                path="/opslog"
                element={<Navigate to="/operations-log" replace />}
              />
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Routes>
          </BootstrapGate>
        </Suspense>
      </OrganizationProvider>
    </ThemeProvider>
  )
}

export default App
