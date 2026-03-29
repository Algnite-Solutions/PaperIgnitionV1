import { useQuery } from '@tanstack/react-query'
import { getBlogContent, getGlobalBlogContent } from '../api/digests'

export function useBlogContent(paperId: string, username?: string | null) {
  return useQuery<string>({
    queryKey: ['blogContent', paperId, username],
    queryFn: () =>
      username ? getBlogContent(paperId, username) : getGlobalBlogContent(paperId),
    enabled: !!paperId,
    staleTime: 10 * 60 * 1000,
  })
}
