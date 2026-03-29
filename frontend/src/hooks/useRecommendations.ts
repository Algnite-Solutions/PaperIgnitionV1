import { useQuery } from '@tanstack/react-query'
import { getRecommendations, type RecommendedPaper } from '../api/digests'
import { useAuthStore } from '../stores/auth'
import { DEFAULT_FEED_USER } from '../lib/constants'

export function useRecommendations() {
  const user = useAuthStore((s) => s.user)
  const username = user?.username || DEFAULT_FEED_USER

  return useQuery<RecommendedPaper[]>({
    queryKey: ['recommendations', username],
    queryFn: () => getRecommendations(username),
    staleTime: 5 * 60 * 1000,
  })
}
