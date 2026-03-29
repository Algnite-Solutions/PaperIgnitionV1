import { Link } from 'react-router'
import { X, LogOut } from 'lucide-react'
import { AnimatePresence, motion } from 'framer-motion'
import { useAuthStore } from '../../stores/auth'

interface MobileNavProps {
  open: boolean
  onClose: () => void
}

const links = [
  { to: '/', label: 'Explore' },
  { to: '/search', label: 'Search' },
  { to: '/favorites', label: 'Favorites' },
  { to: '/profile', label: 'Profile' },
]

export function MobileNav({ open, onClose }: MobileNavProps) {
  const { isLoggedIn, user, logout } = useAuthStore()

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/40"
            onClick={onClose}
          />
          {/* Drawer */}
          <motion.div
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'spring', damping: 25, stiffness: 300 }}
            className="fixed right-0 top-0 z-50 h-full w-72 bg-white dark:bg-gray-950 shadow-xl"
          >
            <div className="flex h-14 items-center justify-between border-b border-gray-200 dark:border-gray-800 px-4">
              <span className="text-sm font-medium text-gray-500 dark:text-gray-400">
                {isLoggedIn ? user?.username : 'Menu'}
              </span>
              <button
                onClick={onClose}
                className="rounded-lg p-1.5 text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800 cursor-pointer"
              >
                <X size={18} />
              </button>
            </div>

            <nav className="flex flex-col gap-1 p-3">
              {links.map((link) => (
                <Link
                  key={link.to}
                  to={link.to}
                  onClick={onClose}
                  className="rounded-lg px-3 py-2.5 text-sm font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
                >
                  {link.label}
                </Link>
              ))}
            </nav>

            <div className="mt-auto border-t border-gray-200 dark:border-gray-800 p-3">
              {isLoggedIn ? (
                <button
                  onClick={() => {
                    logout()
                    onClose()
                  }}
                  className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-sm font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 cursor-pointer"
                >
                  <LogOut size={16} />
                  Logout
                </button>
              ) : (
                <Link
                  to="/login"
                  onClick={onClose}
                  className="block rounded-lg bg-brand px-3 py-2.5 text-center text-sm font-medium text-white hover:bg-brand-dark"
                >
                  Sign In
                </Link>
              )}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
