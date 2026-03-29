import { Navigate } from 'react-router'
import { LoginForm } from '../components/auth/LoginForm'
import { useAuthStore } from '../stores/auth'

export function LoginPage() {
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn)

  if (isLoggedIn) return <Navigate to="/" replace />

  return (
    <div className="flex min-h-[calc(100vh-8rem)] items-center justify-center px-4">
      <LoginForm />
    </div>
  )
}
