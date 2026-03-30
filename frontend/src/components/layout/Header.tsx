import { Link, useLocation } from 'react-router'
import { LogOut, Menu, User } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useAuthStore } from '../../stores/auth'
import { ThemeToggle } from '../ui/ThemeToggle'
import { MobileNav } from './MobileNav'
import { getMe } from '../../api/users'
import { resendVerification } from '../../api/auth'
import { ApiError } from '../../api/client'

const navLinks = [
  { to: '/', label: 'Explore' },
  { to: '/favorites', label: 'Favorites' },
  { to: '/search', label: 'Search' },
]

export function Header() {
  const { user, isLoggedIn, logout } = useAuthStore()
  const location = useLocation()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [isVerified, setIsVerified] = useState<boolean | null>(null)
  const [nudgeDismissed, setNudgeDismissed] = useState(false)
  const [resendLoading, setResendLoading] = useState(false)
  const [resendMsg, setResendMsg] = useState('')

  useEffect(() => {
    if (!isLoggedIn) {
      setIsVerified(null)
      return
    }
    getMe()
      .then((profile) => setIsVerified(profile.is_verified))
      .catch(() => setIsVerified(null))
  }, [isLoggedIn])

  async function handleResend() {
    setResendLoading(true)
    try {
      await resendVerification()
      setResendMsg('Verification email sent!')
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setResendMsg('Too frequent — try again in 1 minute.')
      } else {
        setResendMsg('Could not resend. Try again later.')
      }
    } finally {
      setResendLoading(false)
    }
  }

  const showNudge = isLoggedIn && isVerified === false && !nudgeDismissed

  return (
    <>
      <header className="sticky top-0 z-40 border-b border-gray-200 dark:border-gray-800 bg-white/80 dark:bg-gray-950/80 backdrop-blur-md">
        {showNudge && (
          <div className="bg-amber-50 dark:bg-amber-900/20 border-b border-amber-200 dark:border-amber-800 px-4 py-2 flex items-center justify-between text-sm text-amber-800 dark:text-amber-300">
            <span>
              Please verify your email to unlock all features.{' '}
              {resendMsg ? (
                <span className="font-medium">{resendMsg}</span>
              ) : (
                <button
                  onClick={handleResend}
                  disabled={resendLoading}
                  className="underline font-medium hover:text-amber-900 dark:hover:text-amber-200 cursor-pointer disabled:opacity-50"
                >
                  {resendLoading ? 'Sending…' : 'Resend'}
                </button>
              )}
            </span>
            <button
              onClick={() => setNudgeDismissed(true)}
              className="ml-4 text-amber-600 dark:text-amber-400 hover:text-amber-900 dark:hover:text-amber-200 cursor-pointer"
              aria-label="Dismiss"
            >
              ✕
            </button>
          </div>
        )}

        <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-4">
          {/* Logo */}
          <Link to="/" className="flex items-center gap-0.5 text-xl font-bold">
            <span className="text-gray-900 dark:text-white">Paper</span>
            <span className="text-brand">Ignition</span>
          </Link>

          {/* Desktop nav */}
          <nav className="hidden items-center gap-1 md:flex">
            {navLinks.map((link) => (
              <Link
                key={link.to}
                to={link.to}
                className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                  location.pathname === link.to
                    ? 'text-brand'
                    : 'text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white'
                }`}
              >
                {link.label}
              </Link>
            ))}
          </nav>

          {/* Right side */}
          <div className="flex items-center gap-2">
            <ThemeToggle />

            {isLoggedIn ? (
              <>
                <Link
                  to="/profile"
                  className="hidden items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white transition-colors md:flex"
                >
                  <User size={16} />
                  {user?.username}
                </Link>
                <button
                  onClick={logout}
                  className="hidden rounded-lg p-2 text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800 transition-colors md:block cursor-pointer"
                  aria-label="Logout"
                >
                  <LogOut size={18} />
                </button>
              </>
            ) : (
              <Link
                to="/login"
                className="hidden rounded-lg bg-brand px-4 py-1.5 text-sm font-medium text-white hover:bg-brand-dark transition-colors md:block"
              >
                Sign In
              </Link>
            )}

            {/* Mobile hamburger */}
            <button
              onClick={() => setMobileOpen(true)}
              className="rounded-lg p-2 text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800 md:hidden cursor-pointer"
              aria-label="Open menu"
            >
              <Menu size={20} />
            </button>
          </div>
        </div>
      </header>

      <MobileNav open={mobileOpen} onClose={() => setMobileOpen(false)} />
    </>
  )
}
