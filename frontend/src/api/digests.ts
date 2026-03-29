import { api } from './client'

export interface RecommendedPaper {
  id: string
  title: string
  authors: string
  abstract: string
  url: string
  submitted: string
  recommendation_date: string
  viewed: boolean
  blog_liked: boolean | null
}

export function getRecommendations(
  username: string,
  limit = 50,
): Promise<RecommendedPaper[]> {
  return api.get<RecommendedPaper[]>(
    `/api/digests/recommendations/${encodeURIComponent(username)}?limit=${limit}`,
  )
}

export function getBlogContent(paperId: string, username: string): Promise<string> {
  return api.get<string>(
    `/api/digests/blog_content/${encodeURIComponent(paperId)}/${encodeURIComponent(username)}`,
  )
}

export function getGlobalBlogContent(paperId: string): Promise<string> {
  return api.get<string>(`/api/papers/content/${encodeURIComponent(paperId)}`)
}

export function updateFeedback(
  paperId: string,
  username: string,
  blogLiked: boolean | null,
): Promise<unknown> {
  return api.put(`/api/digests/recommendations/${encodeURIComponent(paperId)}/feedback`, {
    username,
    blog_liked: blogLiked,
  })
}

export function markViewed(paperId: string): Promise<unknown> {
  return api.post(`/api/digests/${encodeURIComponent(paperId)}/mark-viewed`)
}

export interface PaperMetadata {
  doc_id: string
  title: string
  abstract: string
  authors: string[]
  categories: string[]
  published_date: string
  pdf_path: string
  html_path: string
  comments: string
  has_blog: boolean
}

export function getPaperMetadata(docId: string): Promise<PaperMetadata> {
  return api.get<PaperMetadata>(`/api/papers/metadata/${encodeURIComponent(docId)}`)
}
