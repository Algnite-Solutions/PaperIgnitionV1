import { useState, useEffect, useRef, useCallback } from 'react'
import { Link, useNavigate } from 'react-router'
import { LogIn } from 'lucide-react'
import { useRecommendations } from '../hooks/useRecommendations'
import { useAuthStore } from '../stores/auth'
import { PaperCard } from '../components/paper/PaperCard'
import { PaperCardSkeleton } from '../components/paper/PaperCardSkeleton'
import { PAPERS_PER_PAGE } from '../lib/constants'
import type { RecommendedPaper } from '../api/digests'

function deduplicatePapers(papers: RecommendedPaper[]): RecommendedPaper[] {
  const seen = new Map<string, RecommendedPaper>()
  for (const p of papers) {
    const existing = seen.get(p.id)
    if (!existing || p.recommendation_date > existing.recommendation_date) {
      seen.set(p.id, p)
    }
  }
  return Array.from(seen.values())
}

export function FeedPage() {
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn)
  const { demoLogin } = useAuthStore()
  const navigate = useNavigate()
  const [demoLoading, setDemoLoading] = useState(false)

  async function handleDemo() {
    setDemoLoading(true)
    try {
      await demoLogin()
      navigate('/')
    } catch {
      // ignore
    } finally {
      setDemoLoading(false)
    }
  }
  const { data: rawPapers, isLoading, error } = useRecommendations()
  const [displayCount, setDisplayCount] = useState(PAPERS_PER_PAGE)
  const sentinelRef = useRef<HTMLDivElement>(null)

  const papers = rawPapers ? deduplicatePapers(rawPapers) : []
  const visiblePapers = papers.slice(0, displayCount)
  const hasMore = displayCount < papers.length

  const loadMore = useCallback(() => {
    setDisplayCount((prev) => Math.min(prev + PAPERS_PER_PAGE, papers.length))
  }, [papers.length])

  useEffect(() => {
    const sentinel = sentinelRef.current
    if (!sentinel) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasMore) loadMore()
      },
      { rootMargin: '200px' },
    )
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [hasMore, loadMore])

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      {/* Login banner */}
      {!isLoggedIn && (
        <div className="mb-6 flex items-center justify-between rounded-xl border border-blue-200 dark:border-blue-900 bg-blue-50 dark:bg-blue-950/30 px-5 py-4">
          <div>
            <p className="text-sm font-medium text-blue-900 dark:text-blue-200">
              Get personalized recommendations
            </p>
            <p className="text-xs text-blue-600 dark:text-blue-400">
              Sign in to see papers tailored to your research interests
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleDemo}
              disabled={demoLoading}
              className="inline-flex items-center gap-1.5 rounded-lg border border-blue-300 dark:border-blue-700 px-4 py-2 text-sm font-medium text-blue-700 dark:text-blue-300 hover:bg-blue-100 dark:hover:bg-blue-900/30 transition-colors disabled:opacity-60"
            >
              Try Demo
            </button>
            <Link
              to="/login"
              className="inline-flex items-center gap-1.5 rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-dark transition-colors"
            >
              <LogIn size={14} />
              Sign In
            </Link>
          </div>
        </div>
      )}

      {/* Page title */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
          {isLoggedIn ? 'Your Daily Feed' : 'Featured Papers'}
        </h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          {isLoggedIn
            ? 'AI-curated papers based on your research interests'
            : 'Explore AI-generated summaries of recent papers'}
        </p>
      </div>

      {/* Loading state */}
      {isLoading && (
        <div className="space-y-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <PaperCardSkeleton key={i} />
          ))}
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="rounded-xl border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-950/30 px-5 py-8 text-center">
          <p className="text-sm text-red-600 dark:text-red-400">
            Failed to load papers. Please try again later.
          </p>
        </div>
      )}

      {/* Paper list */}
      {!isLoading && !error && (
        <div className="space-y-4">
          {visiblePapers.map((paper) => (
            <PaperCard key={paper.id} paper={paper} />
          ))}

          {/* Infinite scroll sentinel */}
          {hasMore && (
            <div ref={sentinelRef} className="py-4 text-center">
              <p className="text-sm text-gray-400">Loading more papers...</p>
            </div>
          )}

          {/* Empty state */}
          {papers.length === 0 && (
            <div className="py-16 text-center">
              <p className="text-gray-500 dark:text-gray-400">No papers found.</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
