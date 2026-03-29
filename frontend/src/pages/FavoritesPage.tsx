import { useNavigate } from 'react-router'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Bookmark, ExternalLink, Trash2, BookOpen } from 'lucide-react'
import { getFavorites, removeFavorite, type FavoritePaper } from '../api/favorites'
import { useAuthStore } from '../stores/auth'
import { Spinner } from '../components/ui/Spinner'
import { toast } from '../components/ui/Toast'
import { truncateText } from '../lib/utils'

function FavoriteCard({ paper }: { paper: FavoritePaper }) {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const queryClient = useQueryClient()

  const remove = useMutation({
    mutationFn: () => removeFavorite(paper.paper_id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['favorites'] })
      queryClient.invalidateQueries({ queryKey: ['favoriteIds'] })
      toast('success', 'Removed from favorites')
    },
  })

  function handleClick() {
    const params = new URLSearchParams()
    if (user?.username) params.set('username', user.username)
    navigate(`/paper/${paper.paper_id}?${params.toString()}`)
  }

  return (
    <article className="group rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 transition-all hover:shadow-md hover:border-gray-300 dark:hover:border-gray-700">
      <div className="flex items-start justify-between gap-3">
        <h2
          onClick={handleClick}
          className="text-lg font-semibold leading-snug text-gray-900 dark:text-white group-hover:text-brand transition-colors cursor-pointer"
        >
          {paper.title}
        </h2>
        <Bookmark size={16} className="shrink-0 text-amber-500 mt-1" fill="currentColor" />
      </div>

      <p className="mt-1.5 text-sm text-gray-500 dark:text-gray-400 line-clamp-1">
        {paper.authors}
      </p>

      <p className="mt-3 text-sm leading-relaxed text-gray-600 dark:text-gray-300 line-clamp-3">
        {truncateText(paper.abstract, 300)}
      </p>

      <div className="mt-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <button
            onClick={handleClick}
            className="inline-flex items-center gap-1.5 text-xs text-brand hover:text-brand-dark transition-colors cursor-pointer"
          >
            <BookOpen size={12} />
            Read Blog
          </button>
          {paper.url && (
            <a
              href={paper.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
            >
              <ExternalLink size={12} />
              PDF
            </a>
          )}
        </div>

        <button
          onClick={() => remove.mutate()}
          disabled={remove.isPending}
          className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors cursor-pointer"
        >
          <Trash2 size={13} />
          Remove
        </button>
      </div>
    </article>
  )
}

export function FavoritesPage() {
  const { data: favorites, isLoading, error } = useQuery({
    queryKey: ['favorites'],
    queryFn: getFavorites,
    staleTime: 2 * 60 * 1000,
  })

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Favorites</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          Papers you&apos;ve bookmarked for later
        </p>
      </div>

      {isLoading && (
        <div className="flex items-center justify-center py-20">
          <Spinner className="size-8" />
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-950/30 px-5 py-8 text-center">
          <p className="text-sm text-red-600 dark:text-red-400">
            Failed to load favorites.
          </p>
        </div>
      )}

      {favorites && favorites.length === 0 && (
        <div className="py-16 text-center">
          <Bookmark size={40} className="mx-auto text-gray-300 dark:text-gray-700" />
          <p className="mt-4 text-gray-500 dark:text-gray-400">No favorites yet</p>
          <p className="mt-1 text-sm text-gray-400 dark:text-gray-500">
            Bookmark papers from your feed to save them here
          </p>
        </div>
      )}

      {favorites && favorites.length > 0 && (
        <div className="space-y-4">
          {favorites.map((paper) => (
            <FavoriteCard key={paper.paper_id} paper={paper} />
          ))}
        </div>
      )}
    </div>
  )
}
