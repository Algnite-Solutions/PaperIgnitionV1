import { useMemo } from 'react'
import { useParams, useSearchParams, useNavigate } from 'react-router'
import { ArrowLeft, ExternalLink, Bookmark, Share2 } from 'lucide-react'
import { useBlogContent } from '../hooks/useBlogContent'
import { useFavorites } from '../hooks/useFavorites'
import { useToggleFavorite } from '../hooks/useToggleFavorite'
import { useAuthStore } from '../stores/auth'
import { BlogRenderer } from '../components/paper/BlogRenderer'
import { Spinner } from '../components/ui/Spinner'
import { toast } from '../components/ui/Toast'
import { useQuery } from '@tanstack/react-query'
import { getPaperMetadata } from '../api/digests'

/** Extract the blog title and return [blogTitle, remainingContent].
 *  Blog content may start with:
 *    (a) `# Blog Title` — use it
 *    (b) `Original Paper Title\n\n## Blog Headline` — skip the original title, use ## as blog title
 *    (c) `Blog Title (plain text)\n\n## Section` — use the plain text if it differs from metadata title
 *  We always prefer the first ## heading as the blog title when present. */
function extractBlogTitle(md: string, metadataTitle?: string): [string | null, string] {
  // Case 1: explicit # heading (single #, not ##)
  const h1Match = md.match(/^#(?!#)\s+(.+)$/m)
  if (h1Match) {
    const title = h1Match[1].trim()
    const remaining = md.slice(0, h1Match.index) + md.slice(h1Match.index! + h1Match[0].length)
    return [title, remaining.trimStart()]
  }

  // Case 2: first line is plain text, followed by ## heading — use ## as blog title, drop first line
  const lines = md.split('\n')
  const firstLine = lines[0]?.trim()
  if (firstLine && !firstLine.startsWith('#')) {
    // Find the first ## heading
    const h2Match = md.match(/^##\s+(.+)$/m)
    if (h2Match) {
      const blogTitle = h2Match[1].trim()
      // Remove the first plain-text line and the ## heading line from content
      const remaining = md.slice(0, h2Match.index) + md.slice(h2Match.index! + h2Match[0].length)
      // Also strip the leading original-title line
      const cleaned = remaining.replace(firstLine, '').trimStart()
      return [blogTitle, cleaned]
    }

    // No ## heading — use the first line only if it differs from the metadata title
    if (metadataTitle && firstLine.toLowerCase() !== metadataTitle.toLowerCase()) {
      const rest = lines.slice(1).join('\n').trimStart()
      return [firstLine, rest]
    }
  }

  return [null, md]
}

export function PaperPage() {
  const { id } = useParams<{ id: string }>()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const username = searchParams.get('username')
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn)

  const paperId = id || ''
  const { data: content, isLoading: contentLoading, error: contentError } = useBlogContent(paperId, username)
  const { data: metadata } = useQuery({
    queryKey: ['paperMetadata', paperId],
    queryFn: () => getPaperMetadata(paperId),
    enabled: !!paperId,
    staleTime: 30 * 60 * 1000,
  })

  const [blogTitle, blogBody] = useMemo(() => {
    if (!content) return [null, '']
    return extractBlogTitle(content, metadata?.title)
  }, [content, metadata?.title])

  const { data: favorites = [] } = useFavorites()
  const isFavorited = favorites.some((f) => f.paper_id === paperId)
  const toggleFavorite = useToggleFavorite()

  function handleFavorite() {
    if (!isLoggedIn) {
      toast('error', 'Please sign in to bookmark papers')
      return
    }
    toggleFavorite.mutate({
      paperId,
      isFavorited,
      paper: metadata
        ? {
            title: metadata.title,
            authors: metadata.authors.join(', '),
            abstract: metadata.abstract,
            url: `https://arxiv.org/pdf/${metadata.doc_id}`,
          }
        : undefined,
    })
  }

  function handleShare() {
    const url = window.location.href
    navigator.clipboard.writeText(url).then(() => toast('success', 'Link copied to clipboard'))
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      {/* Back button */}
      <button
        onClick={() => navigate(-1)}
        className="mb-6 inline-flex items-center gap-1.5 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors cursor-pointer"
      >
        <ArrowLeft size={16} />
        Back
      </button>

      {/* Header: blog title is hero, original paper title + authors are subtitles */}
      <header className="mb-8">
        {/* Blog title (AI-generated) — main hero */}
        {blogTitle && (
          <h1 className="text-3xl font-bold leading-tight text-gray-900 dark:text-white md:text-4xl">
            {blogTitle}
          </h1>
        )}

        {/* Original paper title — subtitle */}
        {metadata && (
          <div className={blogTitle ? 'mt-4' : ''}>
            {!blogTitle && (
              <h1 className="text-2xl font-bold leading-tight text-gray-900 dark:text-white md:text-3xl">
                {metadata.title}
              </h1>
            )}
            {blogTitle && (
              <p className="text-base text-gray-500 dark:text-gray-400">
                {metadata.title}
              </p>
            )}
            <p className="mt-1.5 text-sm text-gray-400 dark:text-gray-500">
              {metadata.authors.join(', ')}
            </p>
            <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">
              Published {metadata.published_date}
            </p>
          </div>
        )}

        {/* Action buttons */}
        <div className="mt-5 flex flex-wrap items-center gap-2">
          <button
            onClick={handleFavorite}
            disabled={!metadata && !isFavorited}
            className={`inline-flex items-center gap-1.5 rounded-lg border px-3.5 py-2 text-sm font-medium transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed ${
              isFavorited
                ? 'border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-400'
                : 'border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-800'
            }`}
          >
            <Bookmark size={14} fill={isFavorited ? 'currentColor' : 'none'} />
            {isFavorited ? 'Saved' : 'Save Paper'}
          </button>

          <a
            href={`https://arxiv.org/pdf/${paperId}`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 dark:border-gray-600 px-3.5 py-2 text-sm font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
          >
            <ExternalLink size={14} />
            PDF
          </a>

          <button
            onClick={handleShare}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 dark:border-gray-600 px-3.5 py-2 text-sm font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors cursor-pointer"
          >
            <Share2 size={14} />
            Share
          </button>
        </div>
      </header>

      {/* Divider */}
      <hr className="mb-8 border-gray-200 dark:border-gray-800" />

      {/* Blog content */}
      {contentLoading && (
        <div className="flex items-center justify-center py-20">
          <Spinner className="size-8" />
        </div>
      )}

      {contentError && (
        <div className="rounded-xl border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-950/30 px-5 py-8 text-center">
          <p className="text-sm text-red-600 dark:text-red-400">
            Failed to load blog content. This paper may not have a summary yet.
          </p>
        </div>
      )}

      {content && <BlogRenderer content={blogBody} />}
    </div>
  )
}
