import React from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';

/** Detects Supabase magic-link / invite / recovery flows via URL params */
const isSupabaseAuthFlow = () =>
  (window.location.hash + window.location.search).includes('type=recovery') ||
  (window.location.hash + window.location.search).includes('type=signup') ||
  (window.location.hash + window.location.search).includes('type=invite');

/**
 * Layout-route guard. Wraps all authenticated routes.
 * - While auth is resolving: shows a full-screen spinner.
 * - If Supabase auth-flow URL detected: redirects to /login so LoginView
 *   can handle the token exchange (password reset, invite accept, etc.).
 * - If no authenticated user/profile: redirects to /login, preserving
 *   the intended destination in `location.state.from` for post-login redirect.
 * - Otherwise: renders child routes via <Outlet />.
 */
const ProtectedRoute: React.FC = () => {
  const { user, profile, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-50 dark:bg-gray-900">
        <div className="text-center">
          <Loader2 className="animate-spin mx-auto text-blue-500 mb-4" size={40} />
          <p className="text-gray-500 dark:text-gray-400 text-sm">Cargando...</p>
        </div>
      </div>
    );
  }

  if (!user || !profile || isSupabaseAuthFlow()) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <Outlet />;
};

export default ProtectedRoute;
