import { useMutation, useQueryClient } from '@tanstack/react-query'
import { updateFeedback } from '../api/digests'
import type { RecommendedPaper } from '../api/digests'
import { useAuthStore } from '../stores/auth'
import { DEFAULT_FEED_USER } from '../lib/constants'

export function useFeedback() {
  const queryClient = useQueryClient()
  const user = useAuthStore((s) => s.user)
  const username = user?.username || DEFAULT_FEED_USER

  return useMutation({
    mutationFn: ({ paperId, liked }: { paperId: string; liked: boolean | null }) =>
      updateFeedback(paperId, username, liked),
    onMutate: async ({ paperId, liked }) => {
      const key = ['recommendations', username]
      await queryClient.cancelQueries({ queryKey: key })
      const prev = queryClient.getQueryData<RecommendedPaper[]>(key)
      if (prev) {
        queryClient.setQueryData<RecommendedPaper[]>(
          key,
          prev.map((p) => (p.id === paperId ? { ...p, blog_liked: liked } : p)),
        )
      }
      return { prev }
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) {
        queryClient.setQueryData(['recommendations', username], ctx.prev)
      }
    },
  })
}
