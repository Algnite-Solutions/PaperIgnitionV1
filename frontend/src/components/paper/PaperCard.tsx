import { useNavigate } from 'react-router'
import { ExternalLink } from 'lucide-react'
import { Badge } from '../ui/Badge'
import { PaperActions } from './PaperActions'
import { formatAuthors, formatDate, truncateText } from '../../lib/utils'
import { useAuthStore } from '../../stores/auth'
import { markViewed } from '../../api/digests'
import type { RecommendedPaper } from '../../api/digests'

interface PaperCardProps {
  paper: RecommendedPaper
}

export function PaperCard({ paper }: PaperCardProps) {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn)

  function handleClick() {
    if (isLoggedIn) {
      markViewed(paper.id).catch(() => {})
    }
    const params = new URLSearchParams()
    if (user?.username) params.set('username', user.username)
    navigate(`/paper/${paper.id}?${params.toString()}`)
  }

  return (
    <article
      onClick={handleClick}
      className="group cursor-pointer rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 transition-all hover:shadow-md hover:border-gray-300 dark:hover:border-gray-700"
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-lg font-semibold leading-snug text-gray-900 dark:text-white group-hover:text-brand transition-colors">
          {paper.title}
        </h2>
        <Badge variant={paper.viewed ? 'viewed' : 'new'}>
          {paper.viewed ? 'Viewed' : 'New'}
        </Badge>
      </div>

      {/* Authors */}
      <p className="mt-1.5 text-sm text-gray-500 dark:text-gray-400 line-clamp-1">
        {formatAuthors(paper.authors)}
      </p>

      {/* Abstract */}
      <p className="mt-3 text-sm leading-relaxed text-gray-600 dark:text-gray-300 line-clamp-3">
        {truncateText(paper.abstract, 300)}
      </p>

      {/* Meta + actions row */}
      <div className="mt-4 flex items-center justify-between">
        <div className="flex items-center gap-3 text-xs text-gray-400 dark:text-gray-500">
          <span>Published {formatDate(paper.submitted)}</span>
          <span className="text-gray-300 dark:text-gray-700">|</span>
          <span>Recommended {formatDate(paper.recommendation_date)}</span>
          <a
            href={paper.url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="inline-flex items-center gap-1 text-brand hover:text-brand-dark transition-colors"
          >
            <ExternalLink size={12} />
            PDF
          </a>
        </div>

        <PaperActions
          paperId={paper.id}
          blogLiked={paper.blog_liked}
          paper={{
            title: paper.title,
            authors: formatAuthors(paper.authors),
            abstract: paper.abstract,
            url: paper.url,
          }}
        />
      </div>
    </article>
  )
}
