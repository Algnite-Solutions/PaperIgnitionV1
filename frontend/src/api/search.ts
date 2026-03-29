import { api } from './client'

export interface SimilarPaper {
  doc_id: string
  title: string
  abstract: string
  authors: string[]
  categories: string[]
  published_date: string | null
  pdf_path: string | null
  html_path: string | null
  similarity: number
}

export interface SearchResponse {
  results: SimilarPaper[]
  query: string
  total: number
}

export type SearchStrategy = 'bm25' | 'embedding'

export async function searchPapers(
  query: string,
  strategy: SearchStrategy = 'bm25',
  topK = 10,
): Promise<{ data: SearchResponse; elapsed: number }> {
  const endpoint =
    strategy === 'bm25'
      ? '/api/papers/find_similar_bm25'
      : '/api/papers/find_similar'

  const start = performance.now()
  const data = await api.post<SearchResponse>(endpoint, {
    query,
    top_k: topK,
    strategy: strategy === 'embedding' ? 'tf-idf' : undefined,
  })
  const elapsed = Math.round(performance.now() - start)

  return { data, elapsed }
}
