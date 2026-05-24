import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Save, Globe, Edit3, X, Zap, Key, Copy, Trash2 } from 'lucide-react'
import { getMe, updateProfile, triggerBoost, listApiKeys, createApiKey, revokeApiKey, deleteApiKey, type UserProfile } from '../api/users'
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
      <EditableChipList
        label="Ranking Heuristics"
        items={profileJson?.ranking_heuristics ?? []}
        profileJson={(profileJson ?? {}) as Record<string, unknown>}
        fieldKey="ranking_heuristics"
        placeholder="e.g., prefer empirical over theoretical"
        successMessage="Ranking heuristics updated"
      />

      {/* Negative Constraints */}
      <EditableChipList
        label="Negative Constraints"
        items={profileJson?.negative_constraints ?? []}
        profileJson={(profileJson ?? {}) as Record<string, unknown>}
        fieldKey="negative_constraints"
        placeholder="e.g., surveys without experiments"
        successMessage="Constraints updated"
      />
    </section>
  )
}

function EditableChipList({
  label,
  items,
  profileJson,
  fieldKey,
  placeholder,
  successMessage,
}: {
  label: string
  items: string[]
  profileJson: Record<string, unknown>
  fieldKey: string
  placeholder: string
  successMessage: string
}) {
  const [localItems, setLocalItems] = useState(items)
  const [adding, setAdding] = useState(false)
  const [newText, setNewText] = useState('')
  const queryClient = useQueryClient()

  const save = useMutation({
    mutationFn: (updated: string[]) =>
      updateProfile({ profile_json: { ...profileJson, [fieldKey]: updated } }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['profile'] })
      toast('success', successMessage)
    },
    onError: () => toast('error', 'Failed to update'),
  })

  function handleRemove(index: number) {
    const updated = localItems.filter((_, i) => i !== index)
    setLocalItems(updated)
    save.mutate(updated)
  }

  function handleAdd() {
    if (!newText.trim()) return
    const updated = [...localItems, newText.trim()]
    setLocalItems(updated)
    setNewText('')
    setAdding(false)
    save.mutate(updated)
  }

  return (
    <div>
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300">{label}</h3>
        <button
          onClick={() => setAdding(true)}
          className="text-xs text-brand hover:text-brand-dark cursor-pointer"
        >
          + Add
        </button>
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        {localItems.map((c, i) => (
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
        {localItems.length === 0 && !adding && (
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
            placeholder={placeholder}
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

function BoosterSection({ profile }: { profile: UserProfile }) {
  const queryClient = useQueryClient()
  const booster = profile.booster_status
  const count = booster?.new_likes_count ?? 0
  const eligible = booster?.eligible ?? false
  const requested = booster?.requested ?? false
  const poolSize = booster?.pool_size ?? 0

  const boost = useMutation({
    mutationFn: triggerBoost,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['profile'] })
      toast('success', 'Profile boost scheduled for tonight!')
    },
    onError: () => toast('error', 'Failed to schedule boost'),
  })

  return (
    <section className="rounded-xl border border-indigo-200 dark:border-indigo-900/50 bg-gradient-to-br from-indigo-50/60 to-purple-50/60 dark:from-indigo-950/30 dark:to-purple-950/30 p-5">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-1">Customization Booster</h2>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-2">
        Like papers you find useful. Every 5 new likes unlocks a boost — AI will analyze your reading patterns and craft a smarter personal profile.
      </p>
      {poolSize > 0 && (
        <p className="text-xs text-indigo-600 dark:text-indigo-400 mb-4">
          Profile optimized from {poolSize} candidates
        </p>
      )}

      {requested ? (
        <button
          disabled
          className="w-full flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 border border-amber-200 dark:border-amber-800 cursor-default"
        >
          <Zap size={15} />
          Boost Scheduled for Tonight
        </button>
      ) : eligible ? (
        <button
          onClick={() => boost.mutate()}
          disabled={boost.isPending}
          className="w-full flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold bg-gradient-to-r from-indigo-500 to-purple-500 hover:from-indigo-600 hover:to-purple-600 text-white shadow-sm shadow-indigo-200 dark:shadow-indigo-900/50 transition-all disabled:opacity-60 cursor-pointer"
        >
          {boost.isPending ? <Spinner className="size-4" /> : <Zap size={15} />}
          Boost My Profile
        </button>
      ) : (
        <button
          disabled
          className="w-full flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold bg-gray-100 dark:bg-gray-800 text-gray-400 dark:text-gray-500 cursor-default"
        >
          <Zap size={15} />
          Boost My Profile
          <span className="ml-auto rounded-full bg-gray-200 dark:bg-gray-700 px-2 py-0.5 text-xs font-bold text-gray-500 dark:text-gray-400">
            {count} / 5
          </span>
        </button>
      )}
    </section>
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

function ApiKeysSection() {
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [newKeyName, setNewKeyName] = useState('')
  const [createdKey, setCreatedKey] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const { data: keys = [], isLoading } = useQuery({
    queryKey: ['api-keys'],
    queryFn: listApiKeys,
  })

  const create = useMutation({
    mutationFn: (name: string) => createApiKey(name),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
      setCreatedKey(data.key)
      setNewKeyName('')
      setCreating(false)
    },
    onError: () => toast('error', 'Failed to create API key'),
  })

  const revoke = useMutation({
    mutationFn: (id: number) => revokeApiKey(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
      toast('success', 'API key revoked')
    },
    onError: () => toast('error', 'Failed to revoke key'),
  })

  const remove = useMutation({
    mutationFn: (id: number) => deleteApiKey(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
      toast('success', 'API key deleted')
    },
    onError: () => toast('error', 'Failed to delete key'),
  })

  function copyKey() {
    if (createdKey) {
      navigator.clipboard.writeText(createdKey)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  return (
    <section className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Key size={18} className="text-gray-500" />
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">API Keys</h2>
        </div>
        {!creating && (
          <button
            onClick={() => setCreating(true)}
            className="text-sm text-brand hover:text-brand-dark cursor-pointer"
          >
            + Create New Key
          </button>
        )}
      </div>
      <p className="text-sm text-gray-500 dark:text-gray-400">
        API keys allow AI agents to search papers and read your digest on your behalf. Keys start with <code className="text-xs bg-gray-100 dark:bg-gray-800 px-1 rounded">pi_live_</code>.
      </p>

      {creating && (
        <div className="flex items-center gap-2">
          <input
            value={newKeyName}
            onChange={(e) => setNewKeyName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && newKeyName.trim() && create.mutate(newKeyName.trim())}
            className="flex-1 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm outline-none focus:border-brand"
            placeholder="Key name (e.g. my-agent)"
            autoFocus
          />
          <Button onClick={() => create.mutate(newKeyName.trim())} disabled={!newKeyName.trim() || create.isPending}>
            {create.isPending ? <Spinner className="size-4" /> : 'Create'}
          </Button>
          <button onClick={() => { setCreating(false); setNewKeyName('') }} className="text-gray-400 hover:text-gray-600 cursor-pointer">
            <X size={16} />
          </button>
        </div>
      )}

      {createdKey && (
        <div className="rounded-lg border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/30 p-4 space-y-2">
          <p className="text-sm font-medium text-amber-800 dark:text-amber-300">
            Copy your API key now — you won&apos;t be able to see it again!
          </p>
          <div className="flex items-center gap-2">
            <code className="flex-1 text-xs bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded px-3 py-2 font-mono break-all">
              {createdKey}
            </code>
            <button
              onClick={copyKey}
              className="shrink-0 rounded-lg border border-gray-300 dark:border-gray-600 px-3 py-2 text-sm hover:bg-gray-50 dark:hover:bg-gray-800 cursor-pointer"
            >
              {copied ? 'Copied!' : <Copy size={14} />}
            </button>
          </div>
          <button
            onClick={() => setCreatedKey(null)}
            className="text-xs text-amber-700 dark:text-amber-400 hover:underline cursor-pointer"
          >
            I&apos;ve saved my key — dismiss
          </button>
        </div>
      )}

      {isLoading ? (
        <div className="flex justify-center py-4"><Spinner className="size-5" /></div>
      ) : keys.length === 0 ? (
        <p className="text-sm text-gray-400 italic py-2">No API keys yet</p>
      ) : (
        <div className="space-y-2">
          {keys.map((k) => (
            <div
              key={k.id}
              className="flex items-center gap-3 rounded-lg border border-gray-200 dark:border-gray-700 px-4 py-3"
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-gray-900 dark:text-white truncate">{k.name}</span>
                  {k.revoked_at ? (
                    <span className="shrink-0 rounded-full bg-red-100 dark:bg-red-900/30 px-2 py-0.5 text-xs text-red-600 dark:text-red-400">
                      Revoked
                    </span>
                  ) : (
                    <span className="shrink-0 rounded-full bg-green-100 dark:bg-green-900/30 px-2 py-0.5 text-xs text-green-600 dark:text-green-400">
                      Active
                    </span>
                  )}
                </div>
                <p className="text-xs text-gray-400 font-mono mt-0.5">
                  {k.key_prefix}...
                  <span className="ml-3 text-gray-400">
                    Created {k.created_at ? new Date(k.created_at).toLocaleDateString() : '—'}
                  </span>
                  {k.last_used_at && (
                    <span className="ml-3 text-gray-400">
                      Last used {new Date(k.last_used_at).toLocaleDateString()}
                    </span>
                  )}
                </p>
              </div>
              <div className="flex items-center gap-1">
                {!k.revoked_at && (
                  <button
                    onClick={() => {
                      if (confirm('Revoke this API key? Agents using it will lose access.')) revoke.mutate(k.id)
                    }}
                    className="rounded-lg px-2 py-1 text-xs text-amber-600 hover:bg-amber-50 dark:hover:bg-amber-950/30 cursor-pointer"
                    disabled={revoke.isPending}
                  >
                    Revoke
                  </button>
                )}
                {k.revoked_at && (
                  <button
                    onClick={() => {
                      if (confirm('Permanently delete this key?')) remove.mutate(k.id)
                    }}
                    className="rounded-lg px-2 py-1 text-xs text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30 cursor-pointer"
                    disabled={remove.isPending}
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
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

      {/* Customization Booster */}
      <BoosterSection profile={profile} />

      {/* Research interests */}
      <InterestsSection profile={profile} />

      {/* Blog language */}
      <BlogLanguageSection profile={profile} />

      {/* System profile */}
      <SystemProfileSection profile={profile} />

      {/* API Keys */}
      <ApiKeysSection />
    </div>
  )
}
