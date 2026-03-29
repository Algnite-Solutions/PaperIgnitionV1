import { Navigate } from 'react-router'
import { RegisterForm } from '../components/auth/RegisterForm'
import { useAuthStore } from '../stores/auth'

export function RegisterPage() {
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn)

  if (isLoggedIn) return <Navigate to="/" replace />

  return (
    <div className="flex min-h-[calc(100vh-8rem)] items-center justify-center px-4">
      <RegisterForm />
    </div>
  )
}
