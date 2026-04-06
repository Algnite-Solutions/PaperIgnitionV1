import { useMutation, useQueryClient } from '@tanstack/react-query'
import { addFavorite, removeFavorite, type FavoritePaper } from '../api/favorites'

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
    onMutate: async ({ paperId, isFavorited, paper }) => {
      await queryClient.cancelQueries({ queryKey: ['favorites'] })
      const prev = queryClient.getQueryData<FavoritePaper[]>(['favorites']) || []
      let next: FavoritePaper[]
      if (isFavorited) {
        next = prev.filter((f) => f.paper_id !== paperId)
      } else if (paper) {
        next = [{ paper_id: paperId, ...paper }, ...prev]
      } else {
        next = prev
      }
      queryClient.setQueryData(['favorites'], next)
      return { prev }
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) queryClient.setQueryData(['favorites'], ctx.prev)
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['favorites'] })
    },
  })
}
