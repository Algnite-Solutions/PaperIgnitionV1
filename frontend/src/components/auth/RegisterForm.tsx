import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { useAuthStore } from '../../stores/auth'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'
import { Spinner } from '../ui/Spinner'
import { ApiError } from '../../api/client'

export function RegisterForm() {
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [registered, setRegistered] = useState(false)

  const { register } = useAuthStore()
  const navigate = useNavigate()

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')

    if (password.length < 6) {
      setError('Password must be at least 6 characters')
      return
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match')
      return
    }

    setLoading(true)
    try {
      await register(email, password, username)
      setRegistered(true)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.status === 400 ? 'Email already registered' : err.message)
      } else {
        setError('Registration failed. Please try again.')
      }
    } finally {
      setLoading(false)
    }
  }

  if (registered) {
    return (
      <div className="w-full max-w-sm space-y-6 text-center">
        <div className="text-5xl">📧</div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Check your email</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          We sent a verification link to <strong>{email}</strong>. Click the link to verify your account.
        </p>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          You can still use the app while unverified.
        </p>
        <button
          onClick={() => navigate('/')}
          className="inline-block rounded-lg bg-brand px-6 py-2 text-sm font-medium text-white hover:bg-brand-dark transition-colors"
        >
          Continue to Feed
        </button>
      </div>
    )
  }

  return (
    <div className="w-full max-w-sm space-y-6">
      <div className="text-center">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Create an account</h1>
        <p className="mt-1.5 text-sm text-gray-500 dark:text-gray-400">
          Get personalized AI paper recommendations daily
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <Input
          label="Full Name"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="Jane Doe"
          required
        />
        <Input
          label="Email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@example.com"
          required
          autoComplete="email"
        />
        <Input
          label="Password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="At least 6 characters"
          required
          autoComplete="new-password"
        />
        <Input
          label="Confirm Password"
          type="password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          placeholder="Repeat your password"
          required
          autoComplete="new-password"
          error={confirmPassword && password !== confirmPassword ? 'Passwords do not match' : undefined}
        />

        {error && (
          <p className="text-sm text-red-500 bg-red-50 dark:bg-red-900/20 rounded-lg px-3 py-2">
            {error}
          </p>
        )}

        <Button type="submit" className="w-full" disabled={loading}>
          {loading ? <Spinner className="size-4" /> : 'Create Account'}
        </Button>
      </form>

      <p className="text-center text-sm text-gray-500 dark:text-gray-400">
        Already have an account?{' '}
        <Link to="/login" className="font-medium text-brand hover:text-brand-dark">
          Sign in
        </Link>
      </p>
    </div>
  )
}
