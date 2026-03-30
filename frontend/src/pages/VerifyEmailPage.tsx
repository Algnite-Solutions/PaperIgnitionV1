import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { verifyEmail } from '../api/auth'
import { Spinner } from '../components/ui/Spinner'

export function VerifyEmailPage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') ?? ''
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading')
  const [message, setMessage] = useState('')

  useEffect(() => {
    if (!token) {
      setStatus('error')
      setMessage('Missing verification token.')
      return
    }
    verifyEmail(token)
      .then(() => {
        setStatus('success')
        setMessage('Your email has been verified!')
      })
      .catch(() => {
        setStatus('error')
        setMessage('This link is invalid or has expired.')
      })
  }, [token])

  return (
    <div className="flex min-h-[calc(100vh-8rem)] items-center justify-center px-4">
      <div className="w-full max-w-sm space-y-6 text-center">
        {status === 'loading' && (
          <>
            <Spinner className="size-8 mx-auto" />
            <p className="text-gray-500 dark:text-gray-400">Verifying your email…</p>
          </>
        )}
        {status === 'success' && (
          <>
            <div className="text-5xl">✅</div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Email verified!</h1>
            <p className="text-gray-500 dark:text-gray-400">{message}</p>
            <Link
              to="/login"
              className="inline-block rounded-lg bg-brand px-6 py-2 text-sm font-medium text-white hover:bg-brand-dark transition-colors"
            >
              Sign In
            </Link>
          </>
        )}
        {status === 'error' && (
          <>
            <div className="text-5xl">❌</div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Verification failed</h1>
            <p className="text-gray-500 dark:text-gray-400">{message}</p>
            <Link
              to="/login"
              className="inline-block rounded-lg bg-brand px-6 py-2 text-sm font-medium text-white hover:bg-brand-dark transition-colors"
            >
              Back to Login
            </Link>
          </>
        )}
      </div>
    </div>
  )
}
