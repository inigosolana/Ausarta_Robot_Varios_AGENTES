import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { supabase } from '../lib/supabase';
import type { UserProfile, UserPermission, UserRole } from '../types';
import type { User, Session } from '@supabase/supabase-js';

interface AuthContextType {
    user: User | null;
    session: Session | null;
    profile: UserProfile | null;
    permissions: UserPermission[];
    loading: boolean;
    signIn: (email: string, password: string) => Promise<{ error: Error | null }>;
    signUp: (email: string, password: string, fullName: string, role?: UserRole) => Promise<{ error: Error | null }>;
    signOut: () => Promise<void>;
    hasPermission: (module: string) => boolean;
    isRole: (...roles: UserRole[]) => boolean;
    refreshProfile: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const useAuth = () => {
    const context = useContext(AuthContext);
    if (!context) throw new Error('useAuth must be used within AuthProvider');
    return context;
};

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
    const [user, setUser] = useState<User | null>(null);
    const [session, setSession] = useState<Session | null>(null);
    const [profile, setProfile] = useState<UserProfile | null>(null);
    const [permissions, setPermissions] = useState<UserPermission[]>([]);
    const [loading, setLoading] = useState(true);

    // Load profile and permissions
    const loadUserData = async (userId: string) => {
        try {
            // Load profile
            const { data: profileData } = await supabase
                .from('user_profiles')
                .select('*')
                .eq('id', userId)
                .single();

            if (profileData) {
                setProfile(profileData as UserProfile);

                // Load permissions
                const { data: permsData } = await supabase
                    .from('user_permissions')
                    .select('*')
                    .eq('user_id', userId);

                setPermissions((permsData || []) as UserPermission[]);
            }
        } catch (error) {
            console.error('Error loading user data:', error);
        }
    };

    const refreshProfile = async () => {
        if (user) await loadUserData(user.id);
    };

    useEffect(() => {
        // Get initial session
        supabase.auth.getSession().then(({ data: { session: s } }) => {
            setSession(s);
            setUser(s?.user ?? null);
            if (s?.user) {
                loadUserData(s.user.id).finally(() => setLoading(false));
            } else {
                setLoading(false);
            }
        });

        // Listen for auth changes
        const { data: { subscription } } = supabase.auth.onAuthStateChange(
            async (_event, s) => {
                setSession(s);
                setUser(s?.user ?? null);
                if (s?.user) {
                    await loadUserData(s.user.id);
                } else {
                    setProfile(null);
                    setPermissions([]);
                }
            }
        );

        return () => subscription.unsubscribe();
    }, []);

    const signIn = async (email: string, password: string) => {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        return { error: error as Error | null };
    };

    const signUp = async (email: string, password: string, fullName: string, role: UserRole = 'user') => {
        const { error } = await supabase.auth.signUp({
            email,
            password,
            options: {
                data: { full_name: fullName, role }
            }
        });
        return { error: error as Error | null };
    };

    const signOut = async () => {
        await supabase.auth.signOut();
        setUser(null);
        setSession(null);
        setProfile(null);
        setPermissions([]);
    };

    const hasPermission = (module: string): boolean => {
        if (!profile) return false;
        // Superadmins and admins have access to everything
        if (profile.role === 'superadmin' || profile.role === 'admin') return true;
        // Regular users check permissions
        const perm = permissions.find(p => p.module === module);
        return perm?.enabled ?? false;
    };

    const isRole = (...roles: UserRole[]): boolean => {
        if (!profile) return false;
        return roles.includes(profile.role);
    };

    return (
        <AuthContext.Provider value={{
            user, session, profile, permissions, loading,
            signIn, signUp, signOut, hasPermission, isRole, refreshProfile
        }}>
            {children}
        </AuthContext.Provider>
    );
};
