import React, { useEffect, useState } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { supabase } from '../lib/supabase';

// Capture BEFORE Supabase clears the hash (runs once at module load)
const RECOVERY_STORAGE_KEY = 'ausarta_recovery_flow';
(() => {
  const params = window.location.hash + window.location.search;
  if (
    params.includes('type=recovery') ||
    params.includes('type=signup') ||
    params.includes('type=invite')
  ) {
    sessionStorage.setItem(RECOVERY_STORAGE_KEY, '1');
  }
})();

const ProtectedRoute: React.FC = () => {
  const { user, profile, loading } = useAuth();
  const location = useLocation();
  const [pendingRecovery, setPendingRecovery] = useState(
    () => sessionStorage.getItem(RECOVERY_STORAGE_KEY) === '1'
  );

  useEffect(() => {
    const { data: { subscription } } = supabase.auth.onAuthStateChange((event) => {
      if (event === 'PASSWORD_RECOVERY') {
        sessionStorage.setItem(RECOVERY_STORAGE_KEY, '1');
        setPendingRecovery(true);
      }
    });
    return () => subscription.unsubscribe();
  }, []);

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

  if (!user || !profile || pendingRecovery) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <Outlet />;
};

export default ProtectedRoute;
