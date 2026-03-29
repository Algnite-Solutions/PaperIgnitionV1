export function PaperCardSkeleton() {
  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 animate-pulse">
      <div className="flex items-start justify-between gap-3">
        <div className="h-5 w-3/4 rounded bg-gray-200 dark:bg-gray-800" />
        <div className="h-5 w-16 rounded-full bg-gray-200 dark:bg-gray-800" />
      </div>
      <div className="mt-2 h-4 w-1/2 rounded bg-gray-100 dark:bg-gray-800" />
      <div className="mt-4 space-y-2">
        <div className="h-3.5 w-full rounded bg-gray-100 dark:bg-gray-800" />
        <div className="h-3.5 w-full rounded bg-gray-100 dark:bg-gray-800" />
        <div className="h-3.5 w-2/3 rounded bg-gray-100 dark:bg-gray-800" />
      </div>
      <div className="mt-4 flex justify-between">
        <div className="h-4 w-1/3 rounded bg-gray-100 dark:bg-gray-800" />
        <div className="flex gap-2">
          <div className="h-7 w-7 rounded bg-gray-100 dark:bg-gray-800" />
          <div className="h-7 w-7 rounded bg-gray-100 dark:bg-gray-800" />
          <div className="h-7 w-7 rounded bg-gray-100 dark:bg-gray-800" />
        </div>
      </div>
    </div>
  )
}
