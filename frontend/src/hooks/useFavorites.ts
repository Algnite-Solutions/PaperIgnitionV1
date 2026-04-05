import { useQuery } from '@tanstack/react-query'
import { getFavorites } from '../api/favorites'
import { useAuthStore } from '../stores/auth'

export function useFavorites() {
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn)

  return useQuery({
    queryKey: ['favorites'],
    queryFn: getFavorites,
    enabled: isLoggedIn,
    staleTime: 5 * 60 * 1000,
    placeholderData: [],
  })
}
