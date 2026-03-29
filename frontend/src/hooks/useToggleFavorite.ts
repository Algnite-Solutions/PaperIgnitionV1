import { useMutation, useQueryClient } from '@tanstack/react-query'
import { addFavorite, removeFavorite } from '../api/favorites'

export function useToggleFavorite() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      paperId,
      isFavorited,
      paper,
    }: {
      paperId: string
      isFavorited: boolean
      paper?: { title: string; authors: string; abstract: string; url: string }
    }) => {
      if (isFavorited) {
        await removeFavorite(paperId)
      } else if (paper) {
        await addFavorite({ paper_id: paperId, ...paper })
      }
    },
    onMutate: async ({ paperId, isFavorited }) => {
      await queryClient.cancelQueries({ queryKey: ['favoriteIds'] })
      const prev = queryClient.getQueryData<string[]>(['favoriteIds']) || []
      const next = isFavorited ? prev.filter((id) => id !== paperId) : [...prev, paperId]
      queryClient.setQueryData(['favoriteIds'], next)
      return { prev }
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) {
        queryClient.setQueryData(['favoriteIds'], ctx.prev)
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['favoriteIds'] })
    },
  })
}
