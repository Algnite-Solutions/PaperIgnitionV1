import { api } from './client'

export interface FavoritePaper {
  paper_id: string
  title: string
  authors: string
  abstract: string
  url: string
}

export function getFavorites(): Promise<FavoritePaper[]> {
  return api.get<FavoritePaper[]>('/api/favorites/list')
}

export function addFavorite(paper: {
  paper_id: string
  title: string
  authors: string
  abstract: string
  url: string
}): Promise<unknown> {
  return api.post('/api/favorites/add', paper)
}

export function removeFavorite(paperId: string): Promise<unknown> {
  return api.delete(`/api/favorites/remove/${encodeURIComponent(paperId)}`)
}
