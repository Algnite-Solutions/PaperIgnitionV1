import { useEffect, useState, useCallback } from 'react'
import { X } from 'lucide-react'

interface ToastMessage {
  id: number
  type: 'success' | 'error'
  text: string
}

let addToast: (type: 'success' | 'error', text: string) => void

export function toast(type: 'success' | 'error', text: string) {
  addToast?.(type, text)
}

let nextId = 0

export function ToastContainer() {
  const [toasts, setToasts] = useState<ToastMessage[]>([])

  const remove = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  useEffect(() => {
    addToast = (type, text) => {
      const id = nextId++
      setToasts((prev) => [...prev, { id, type, text }])
      setTimeout(() => remove(id), 4000)
    }
  }, [remove])

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`flex items-center gap-2 rounded-lg px-4 py-3 text-sm font-medium shadow-lg animate-in slide-in-from-right ${
            t.type === 'success'
              ? 'bg-green-600 text-white'
              : 'bg-red-600 text-white'
          }`}
        >
          <span>{t.text}</span>
          <button onClick={() => remove(t.id)} className="ml-2 cursor-pointer">
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  )
}
