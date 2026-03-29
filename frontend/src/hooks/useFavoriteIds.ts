import { useQuery } from '@tanstack/react-query'
import { getFavoriteIds } from '../api/favorites'
import { useAuthStore } from '../stores/auth'

export function useFavoriteIds() {
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn)

  return useQuery<string[]>({
    queryKey: ['favoriteIds'],
    queryFn: getFavoriteIds,
    enabled: isLoggedIn,
    staleTime: 2 * 60 * 1000,
    placeholderData: [],
  })
}
