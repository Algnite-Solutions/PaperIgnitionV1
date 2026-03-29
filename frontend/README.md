# PaperIgnition Frontend

React + Vite + TypeScript SPA that replaces `beta_frontend/`.

## Quick Start

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173, proxies /api to localhost:8000
```

Requires the backend running on port 8000:
```bash
uvicorn backend.app.main:app --reload --port 8000
```

## How It Works

```
Browser (localhost:5173)
  |
  |-- Static pages ----->  Vite dev server (serves React SPA)
  |
  \-- /api/* requests -->  Vite proxy ----->  FastAPI backend (localhost:8000)
                                                  |
                                                  \--> PostgreSQL (user DB + paper DB)
```

- **Dev**: Vite serves the SPA and proxies `/api/*` to the backend. No Nginx needed.
- **Prod**: `npm run build` -> `dist/` folder -> Nginx serves static files, proxies `/api/*` to uvicorn.

## Tech Stack

| Layer | Library |
|---|---|
| Framework | React 19 + TypeScript |
| Build | Vite 6 |
| Routing | React Router v7 (client-side SPA) |
| Styling | Tailwind CSS v4 + `@tailwindcss/typography` |
| State | Zustand (auth, theme) |
| Data fetching | TanStack Query v5 (caching, optimistic updates) |
| Markdown | react-markdown + remark-math + remark-gfm + rehype-katex + rehype-highlight |
| Animations | Framer Motion |
| Icons | Lucide React |

## Pages

| Route | Page | Description |
|---|---|---|
| `/` | Feed | Daily personalized paper recommendations (or demo feed if not logged in) |
| `/paper/:id` | Blog Reader | AI-generated paper summary with math, code, figures |
| `/search` | Search | BM25 keyword search across all papers |
| `/favorites` | Favorites | Bookmarked papers (requires login) |
| `/profile` | Profile | Research interests, blog language, system profile (requires login) |
| `/login` | Login | Email/password + demo user option |
| `/register` | Register | New account creation |

## Project Structure

```
src/
├── api/          # Backend API calls (auth, digests, favorites, search, users)
├── stores/       # Zustand stores (auth + theme, persisted to localStorage)
├── hooks/        # TanStack Query hooks (recommendations, blog content, favorites)
├── components/
│   ├── layout/   # Header, Footer, MobileNav
│   ├── paper/    # PaperCard, PaperActions, BlogRenderer
│   ├── auth/     # LoginForm, RegisterForm, ProtectedRoute
│   └── ui/       # Button, Input, Badge, Toast, Spinner, ThemeToggle
├── pages/        # Route-level page components
├── lib/          # Constants, utility functions
└── styles/       # Tailwind globals, KaTeX/highlight.js overrides
```

## Key Differences from beta_frontend

- **SPA routing** -- no page reloads when navigating between pages
- **Cached API responses** -- going back to the feed doesn't re-fetch
- **Optimistic updates** -- like/favorite actions update instantly before API responds
- **Math rendering** -- `remark-math` processes `$$...$$` at the AST level (fixes rendering bugs in the old `marked` + KaTeX approach)
- **Dark mode** -- full support with Tailwind `dark:` variants
- **TypeScript** -- all API types and component props are typed

## Commands

```bash
npm run dev       # Start dev server (port 5173)
npm run build     # Production build -> dist/
npm run preview   # Preview production build locally
```

## Proxy Configuration

By default, Vite proxies `/api/*` to `http://localhost:8000`. To proxy to production:

```bash
VITE_API_TARGET=https://www.paperignition.com npm run dev
```

## Production Deployment

1. `npm run build` outputs to `frontend/dist/`
2. Update Nginx `root` from `beta_frontend/` to `frontend/dist/`
3. Nginx continues to proxy `/api/*` to uvicorn on port 8000
4. Add `cd frontend && npm ci && npm run build` to CD pipeline before rsync
