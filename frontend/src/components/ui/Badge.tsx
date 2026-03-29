import type { ReactNode } from 'react'

type BadgeVariant = 'default' | 'success' | 'warning' | 'new' | 'viewed'

const variantClasses: Record<BadgeVariant, string> = {
  default: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  success: 'bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  warning: 'bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  new: 'bg-red-50 text-red-600 dark:bg-red-900/30 dark:text-red-400',
  viewed: 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500',
}

interface BadgeProps {
  variant?: BadgeVariant
  children: ReactNode
}

export function Badge({ variant = 'default', children }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ${variantClasses[variant]}`}
    >
      {children}
    </span>
  )
}
