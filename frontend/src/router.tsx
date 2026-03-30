import { createBrowserRouter, Navigate } from 'react-router'
import { App } from './App'
import { FeedPage } from './pages/FeedPage'
import { PaperPage } from './pages/PaperPage'
import { LoginPage } from './pages/LoginPage'
import { RegisterPage } from './pages/RegisterPage'
import { FavoritesPage } from './pages/FavoritesPage'
import { ProfilePage } from './pages/ProfilePage'
import { SearchPage } from './pages/SearchPage'
import { VerifyEmailPage } from './pages/VerifyEmailPage'
import { ForgotPasswordPage } from './pages/ForgotPasswordPage'
import { ResetPasswordPage } from './pages/ResetPasswordPage'
import { ProtectedRoute } from './components/auth/ProtectedRoute'


export const router = createBrowserRouter([
  {
    element: <App />,
    children: [
      { index: true, element: <FeedPage /> },
      { path: 'paper/:id', element: <PaperPage /> },
      { path: 'login', element: <LoginPage /> },
      { path: 'register', element: <RegisterPage /> },
      { path: 'verify-email', element: <VerifyEmailPage /> },
      { path: 'forgot-password', element: <ForgotPasswordPage /> },
      { path: 'reset-password', element: <ResetPasswordPage /> },
      {
        path: 'favorites',
        element: <ProtectedRoute><FavoritesPage /></ProtectedRoute>,
      },
      {
        path: 'profile',
        element: <ProtectedRoute><ProfilePage /></ProtectedRoute>,
      },
      { path: 'search', element: <SearchPage /> },
      { path: '*', element: <Navigate to="/" replace /> },
    ],
  },
])
