import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export function LoginPage() {
  const navigate = useNavigate()
  const { isAuthenticated, isLoading } = useAuth()

  useEffect(() => {
    if (isAuthenticated) {
      navigate('/dashboard', { replace: true })
    }
  }, [isAuthenticated, navigate])

  const handleLogin = () => {
    // Redirect to backend OAuth login endpoint
    // The backend will handle OAuth flow and redirect back with session cookie
    window.location.href = 'https://imbi.aweber.io/ui/login'
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-lg">Checking authentication...</div>
      </div>
    )
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-slate-50">
      <Card className="w-[400px]">
        <CardHeader className="space-y-1">
          <CardTitle className="text-2xl font-bold">Imbi V2</CardTitle>
          <CardDescription>
            Operational management platform for medium to large environments
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={handleLogin} className="w-full" size="lg">
            Sign in with OAuth
          </Button>
          <p className="text-sm text-muted-foreground mt-4 text-center">
            Click above to authenticate using your organization's OAuth provider
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
