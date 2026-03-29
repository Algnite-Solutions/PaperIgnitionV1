import { ThumbsUp, ThumbsDown, Bookmark } from 'lucide-react'
import { useAuthStore } from '../../stores/auth'
import { useFeedback } from '../../hooks/useFeedback'
import { useToggleFavorite } from '../../hooks/useToggleFavorite'
import { useFavoriteIds } from '../../hooks/useFavoriteIds'
import { toast } from '../ui/Toast'

interface PaperActionsProps {
  paperId: string
  blogLiked: boolean | null
  paper: { title: string; authors: string; abstract: string; url: string }
}

export function PaperActions({ paperId, blogLiked, paper }: PaperActionsProps) {
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn)
  const { data: favoriteIds = [] } = useFavoriteIds()
  const isFavorited = favoriteIds.includes(paperId)
  const feedback = useFeedback()
  const toggle = useToggleFavorite()

  function handleLike() {
    if (!isLoggedIn) { toast('error', 'Please sign in to like papers'); return }
    feedback.mutate({ paperId, liked: blogLiked === true ? null : true })
  }

  function handleDislike() {
    if (!isLoggedIn) { toast('error', 'Please sign in to dislike papers'); return }
    feedback.mutate({ paperId, liked: blogLiked === false ? null : false })
  }

  function handleFavorite(e: React.MouseEvent) {
    e.stopPropagation()
    if (!isLoggedIn) { toast('error', 'Please sign in to bookmark papers'); return }
    toggle.mutate({ paperId, isFavorited, paper })
  }

  return (
    <div className="flex items-center gap-1">
      <button
        onClick={(e) => { e.stopPropagation(); handleLike() }}
        className={`rounded-lg p-1.5 transition-colors cursor-pointer ${
          blogLiked === true
            ? 'text-brand bg-red-50 dark:bg-red-900/20'
            : 'text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
        }`}
        aria-label="Like"
      >
        <ThumbsUp size={16} fill={blogLiked === true ? 'currentColor' : 'none'} />
      </button>

      <button
        onClick={(e) => { e.stopPropagation(); handleDislike() }}
        className={`rounded-lg p-1.5 transition-colors cursor-pointer ${
          blogLiked === false
            ? 'text-gray-700 dark:text-gray-200 bg-gray-100 dark:bg-gray-800'
            : 'text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
        }`}
        aria-label="Dislike"
      >
        <ThumbsDown size={16} fill={blogLiked === false ? 'currentColor' : 'none'} />
      </button>

      <button
        onClick={handleFavorite}
        className={`rounded-lg p-1.5 transition-colors cursor-pointer ${
          isFavorited
            ? 'text-amber-500 bg-amber-50 dark:bg-amber-900/20'
            : 'text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
        }`}
        aria-label={isFavorited ? 'Remove from favorites' : 'Add to favorites'}
      >
        <Bookmark size={16} fill={isFavorited ? 'currentColor' : 'none'} />
      </button>
    </div>
  )
}
