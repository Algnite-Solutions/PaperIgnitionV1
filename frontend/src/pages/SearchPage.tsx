import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'
import { Search, Clock, ExternalLink } from 'lucide-react'
import { searchPapers, type SimilarPaper } from '../api/search'
import { useAuthStore } from '../stores/auth'
import { Button } from '../components/ui/Button'
import { Badge } from '../components/ui/Badge'
import { Spinner } from '../components/ui/Spinner'
import { formatDate, truncateText } from '../lib/utils'

function ResultCard({ paper }: { paper: SimilarPaper }) {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)

  function handleClick() {
    const params = new URLSearchParams()
    if (user?.username) params.set('username', user.username)
    navigate(`/paper/${paper.doc_id}?${params.toString()}`)
  }

  return (
    <article
      onClick={handleClick}
      className="group cursor-pointer rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 transition-all hover:shadow-md hover:border-gray-300 dark:hover:border-gray-700"
    >
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-lg font-semibold leading-snug text-gray-900 dark:text-white group-hover:text-brand transition-colors">
          {paper.title}
        </h2>
        <Badge variant="default">
          {(paper.similarity * 100).toFixed(1)}%
        </Badge>
      </div>

      <p className="mt-1.5 text-sm text-gray-500 dark:text-gray-400 line-clamp-1">
        {Array.isArray(paper.authors) ? paper.authors.join(', ') : paper.authors}
      </p>

      <p className="mt-3 text-sm leading-relaxed text-gray-600 dark:text-gray-300 line-clamp-3">
        {truncateText(paper.abstract, 300)}
      </p>

      <div className="mt-4 flex items-center gap-3 text-xs text-gray-400 dark:text-gray-500">
        {paper.published_date && <span>Published {formatDate(paper.published_date)}</span>}
        {paper.categories?.length > 0 && (
          <>
            <span className="text-gray-300 dark:text-gray-700">|</span>
            <span>{paper.categories.slice(0, 3).join(', ')}</span>
          </>
        )}
        <a
          href={`https://arxiv.org/pdf/${paper.doc_id}`}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="inline-flex items-center gap-1 text-brand hover:text-brand-dark transition-colors"
        >
          <ExternalLink size={12} />
          PDF
        </a>
      </div>
    </article>
  )
}

export function SearchPage() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SimilarPaper[]>([])
  const [elapsed, setElapsed] = useState<number | null>(null)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [searched, setSearched] = useState(false)

  async function handleSearch(e: FormEvent) {
    e.preventDefault()
    if (!query.trim()) return

    setLoading(true)
    setError('')
    setSearched(true)
    try {
      const { data, elapsed: ms } = await searchPapers(query.trim(), 'bm25')
      setResults(data.results)
      setTotal(data.total)
      setElapsed(ms)
    } catch {
      setError('Search failed. Please try again.')
      setResults([])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Search Papers</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          Find papers by topic, keyword, or research question
        </p>
      </div>

      {/* Search form */}
      <form onSubmit={handleSearch} className="space-y-3">
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="w-full rounded-xl border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 pl-10 pr-4 py-3 text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 outline-none focus:border-brand focus:ring-2 focus:ring-brand/20 transition-colors"
              placeholder="e.g., attention mechanism, token compression, KV cache..."
            />
          </div>
          <Button type="submit" disabled={loading || !query.trim()}>
            {loading ? <Spinner className="size-4" /> : 'Search'}
          </Button>
        </div>

      </form>

      {/* Results header */}
      {searched && !loading && !error && (
        <div className="mt-6 mb-4 flex items-center justify-between">
          <p className="text-sm text-gray-500 dark:text-gray-400">
            {total} result{total !== 1 ? 's' : ''} for &quot;{query}&quot;
          </p>
          {elapsed !== null && (
            <span className="inline-flex items-center gap-1 text-xs text-gray-400 dark:text-gray-500">
              <Clock size={12} />
              {elapsed}ms
            </span>
          )}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="mt-6 rounded-xl border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-950/30 px-5 py-8 text-center">
          <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="mt-12 flex items-center justify-center">
          <Spinner className="size-8" />
        </div>
      )}

      {/* Results */}
      {!loading && results.length > 0 && (
        <div className="space-y-4">
          {results.map((paper) => (
            <ResultCard key={paper.doc_id} paper={paper} />
          ))}
        </div>
      )}

      {/* Empty state */}
      {searched && !loading && !error && results.length === 0 && (
        <div className="mt-12 text-center">
          <Search size={40} className="mx-auto text-gray-300 dark:text-gray-700" />
          <p className="mt-4 text-gray-500 dark:text-gray-400">No papers found</p>
          <p className="mt-1 text-sm text-gray-400 dark:text-gray-500">
            Try different keywords or switch search method
          </p>
        </div>
      )}
    </div>
  )
}
