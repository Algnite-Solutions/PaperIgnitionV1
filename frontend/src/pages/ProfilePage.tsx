import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Save, Globe, Edit3, X } from 'lucide-react'
import { getMe, updateProfile, type UserProfile } from '../api/users'
import { Button } from '../components/ui/Button'
import { Spinner } from '../components/ui/Spinner'
import { toast } from '../components/ui/Toast'
import { getInitials } from '../lib/utils'

function StatCard({ value, label }: { value: number; label: string }) {
  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-4 py-5 text-center">
      <p className="text-2xl font-bold text-brand">{value}</p>
      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{label}</p>
    </div>
  )
}

function InterestsSection({ profile }: { profile: UserProfile }) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(profile.research_interests_text || '')
  const queryClient = useQueryClient()

  const update = useMutation({
    mutationFn: () => updateProfile({ research_interests_text: text }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['profile'] })
      setEditing(false)
      toast('success', 'Interests updated')
    },
    onError: () => toast('error', 'Failed to update interests'),
  })

  return (
    <section className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Research Interests</h2>
        {!editing && (
          <button
            onClick={() => { setText(profile.research_interests_text || ''); setEditing(true) }}
            className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 cursor-pointer"
          >
            <Edit3 size={14} />
            Edit
          </button>
        )}
      </div>

      {editing ? (
        <div className="mt-3 space-y-3">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={4}
            className="w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3.5 py-2.5 text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 outline-none focus:border-brand focus:ring-2 focus:ring-brand/20 resize-none"
            placeholder="Describe your research interests in natural language..."
          />
          <div className="flex gap-2">
            <Button onClick={() => update.mutate()} disabled={update.isPending}>
              {update.isPending ? <Spinner className="size-4" /> : <><Save size={14} /> Save</>}
            </Button>
            <Button variant="ghost" onClick={() => setEditing(false)}>
              <X size={14} /> Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className="mt-3">
          {profile.research_interests_text ? (
            <p className="text-sm leading-relaxed text-gray-600 dark:text-gray-300 border-l-2 border-brand pl-3">
              {profile.research_interests_text}
            </p>
          ) : (
            <p className="text-sm text-gray-400 dark:text-gray-500 italic">
              No research interests set. Click Edit to describe what you&apos;re interested in.
            </p>
          )}
        </div>
      )}
    </section>
  )
}

function SystemProfileSection({ profile }: { profile: UserProfile }) {
  const profileJson = profile.profile_json as {
    persona_definition?: string
    ranking_heuristics?: string[]
    negative_constraints?: string[]
  } | null

  return (
    <section className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 space-y-4">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-white">System Profile</h2>

      {/* System Query */}
      <div>
        <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300">System Query</h3>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 rounded-lg px-3 py-2">
          {profile.rewrite_interest || 'Will be generated after more engagement'}
        </p>
      </div>

      {/* Persona */}
      {profileJson?.persona_definition && (
        <div>
          <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300">Persona</h3>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 rounded-lg px-3 py-2">
            {profileJson.persona_definition}
          </p>
        </div>
      )}

      {/* Ranking Heuristics */}
      {profileJson?.ranking_heuristics && profileJson.ranking_heuristics.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300">Ranking Heuristics</h3>
          <ul className="mt-1 space-y-1 text-sm text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 rounded-lg px-3 py-2">
            {profileJson.ranking_heuristics.map((h, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-gray-400">-</span>
                {h}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Negative Constraints */}
      {profileJson?.negative_constraints && profileJson.negative_constraints.length > 0 && (
        <NegativeConstraints
          constraints={profileJson.negative_constraints}
          profileJson={profileJson as Record<string, unknown>}
        />
      )}
    </section>
  )
}

function NegativeConstraints({
  constraints,
  profileJson,
}: {
  constraints: string[]
  profileJson: Record<string, unknown>
}) {
  const [items, setItems] = useState(constraints)
  const [adding, setAdding] = useState(false)
  const [newText, setNewText] = useState('')
  const queryClient = useQueryClient()

  const save = useMutation({
    mutationFn: (updated: string[]) =>
      updateProfile({ profile_json: { ...profileJson, negative_constraints: updated } }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['profile'] })
      toast('success', 'Constraints updated')
    },
    onError: () => toast('error', 'Failed to update'),
  })

  function handleRemove(index: number) {
    const updated = items.filter((_, i) => i !== index)
    setItems(updated)
    save.mutate(updated)
  }

  function handleAdd() {
    if (!newText.trim()) return
    const updated = [...items, newText.trim()]
    setItems(updated)
    setNewText('')
    setAdding(false)
    save.mutate(updated)
  }

  return (
    <div>
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300">Negative Constraints</h3>
        <button
          onClick={() => setAdding(true)}
          className="text-xs text-brand hover:text-brand-dark cursor-pointer"
        >
          + Add
        </button>
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        {items.map((c, i) => (
          <span
            key={i}
            className="inline-flex items-center gap-1 rounded-full bg-gray-100 dark:bg-gray-800 px-3 py-1 text-xs text-gray-600 dark:text-gray-400"
          >
            {c}
            <button
              onClick={() => handleRemove(i)}
              className="ml-0.5 text-gray-400 hover:text-red-500 cursor-pointer"
            >
              <X size={12} />
            </button>
          </span>
        ))}
        {items.length === 0 && !adding && (
          <span className="text-xs text-gray-400 italic">None set</span>
        )}
      </div>
      {adding && (
        <div className="mt-2 flex items-center gap-2">
          <input
            value={newText}
            onChange={(e) => setNewText(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
            className="flex-1 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-1.5 text-sm outline-none focus:border-brand"
            placeholder="e.g., surveys without experiments"
            autoFocus
          />
          <Button onClick={handleAdd} className="py-1.5 text-xs">Add</Button>
          <button onClick={() => setAdding(false)} className="text-gray-400 hover:text-gray-600 cursor-pointer">
            <X size={16} />
          </button>
        </div>
      )}
    </div>
  )
}

function BlogLanguageSection({ profile }: { profile: UserProfile }) {
  const queryClient = useQueryClient()
  const current = profile.blog_language || 'zh'

  const update = useMutation({
    mutationFn: (lang: string) => updateProfile({ blog_language: lang }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['profile'] })
      toast('success', 'Blog language updated')
    },
    onError: () => toast('error', 'Failed to update language'),
  })

  return (
    <section className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5">
      <div className="flex items-center gap-2">
        <Globe size={18} className="text-gray-500" />
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Blog Language</h2>
      </div>
      <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
        Choose the language for AI-generated paper summaries
      </p>
      <div className="mt-3 flex gap-2">
        {[
          { value: 'zh', label: '中文' },
          { value: 'en', label: 'English' },
        ].map((opt) => (
          <button
            key={opt.value}
            onClick={() => update.mutate(opt.value)}
            disabled={update.isPending}
            className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors cursor-pointer ${
              current === opt.value
                ? 'bg-brand text-white'
                : 'border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-800'
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </section>
  )
}

export function ProfilePage() {
  const { data: profile, isLoading, error } = useQuery({
    queryKey: ['profile'],
    queryFn: getMe,
    staleTime: 60 * 1000,
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spinner className="size-8" />
      </div>
    )
  }

  if (error || !profile) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-8">
        <div className="rounded-xl border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-950/30 px-5 py-8 text-center">
          <p className="text-sm text-red-600 dark:text-red-400">Failed to load profile.</p>
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-8 space-y-6">
      {/* Profile header */}
      <div className="rounded-xl bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 p-8 text-center text-white">
        <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-white/20 text-xl font-bold backdrop-blur-sm">
          {getInitials(profile.username)}
        </div>
        <h1 className="mt-3 text-xl font-bold">{profile.username}</h1>
        <p className="mt-0.5 text-sm text-white/70">{profile.email}</p>
      </div>

      {/* Activity stats */}
      <div className="grid grid-cols-3 gap-3">
        <StatCard value={profile.activity_data.viewed_count} label="Papers Read" />
        <StatCard value={profile.activity_data.favorite_count} label="Bookmarked" />
        <StatCard value={profile.activity_data.days_active} label="Days Active" />
      </div>

      {/* Research interests */}
      <InterestsSection profile={profile} />

      {/* Blog language */}
      <BlogLanguageSection profile={profile} />

      {/* System profile */}
      <SystemProfileSection profile={profile} />
    </div>
  )
}
