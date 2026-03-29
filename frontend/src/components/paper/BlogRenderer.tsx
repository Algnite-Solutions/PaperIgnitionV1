import { useEffect, useRef, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkMath from 'remark-math'
import remarkGfm from 'remark-gfm'
import rehypeKatex from 'rehype-katex'
import rehypeHighlight from 'rehype-highlight'
import mediumZoom from 'medium-zoom'
import 'katex/dist/katex.min.css'
import 'highlight.js/styles/github-dark.min.css'

interface BlogRendererProps {
  content: string
}

export function BlogRenderer({ content }: BlogRendererProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  const initZoom = useCallback(() => {
    if (!containerRef.current) return
    const images = containerRef.current.querySelectorAll('img')
    mediumZoom(images, { margin: 24, background: 'rgba(0,0,0,0.85)' })
  }, [])

  useEffect(() => {
    // Small delay to ensure images are rendered
    const timer = setTimeout(initZoom, 200)
    return () => clearTimeout(timer)
  }, [content, initZoom])

  return (
    <div ref={containerRef}>
      <div className="prose prose-gray dark:prose-invert max-w-none prose-headings:scroll-mt-20 prose-a:text-brand prose-a:no-underline hover:prose-a:underline prose-pre:bg-gray-900 prose-pre:dark:bg-gray-800">
        <ReactMarkdown
          remarkPlugins={[remarkMath, remarkGfm]}
          rehypePlugins={[rehypeKatex, rehypeHighlight]}
          components={{
            table: ({ children, ...props }) => (
              <div className="overflow-x-auto -mx-4 px-4">
                <table {...props}>{children}</table>
              </div>
            ),
          }}
        >
          {content}
        </ReactMarkdown>
      </div>
    </div>
  )
}
