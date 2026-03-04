import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { supabase } from '../lib/supabase';
import type { UserProfile, UserPermission, UserRole, Empresa } from '../types';
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
    realProfile: UserProfile | null;
    isPlatformOwner: boolean;
    setSpoofedRole: (role: UserRole | null) => void;
    setSpoofedEmpresa: (empresaId: number | null) => void;
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

    const [realProfile, setRealProfile] = useState<UserProfile | null>(null);

    // Initialize spoofing from localStorage
    const [spoofedRole, setSpoofedRoleState] = useState<UserRole | null>(() => {
        return (localStorage.getItem('spoofedRole') as UserRole) || null;
    });
    const [spoofedEmpresa, setSpoofedEmpresaState] = useState<number | null>(() => {
        const val = localStorage.getItem('spoofedEmpresa');
        return val ? Number(val) : null;
    });

    const setSpoofedRole = (role: UserRole | null) => {
        if (role) localStorage.setItem('spoofedRole', role);
        else localStorage.removeItem('spoofedRole');
        setSpoofedRoleState(role);
    };

    const setSpoofedEmpresa = (empresaId: number | null) => {
        if (empresaId) localStorage.setItem('spoofedEmpresa', empresaId.toString());
        else localStorage.removeItem('spoofedEmpresa');
        setSpoofedEmpresaState(empresaId);
    };

    // Load profile and permissions
    const loadUserData = async (userId: string) => {
        try {
            // Load profile
            const { data: profileData } = await supabase
                .from('user_profiles')
                .select('*, empresas(*)')
                .eq('id', userId)
                .single();

            if (profileData) {
                setRealProfile(profileData as UserProfile);

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

    // Synthesize the effective profile based on spoofing
    useEffect(() => {
        if (!realProfile) {
            setProfile(null);
            return;
        }

        const isActuallyAusarta = realProfile.empresas?.nombre === 'Ausarta' || realProfile.email === 'admin@ausarta.net';
        const canSpoof = (realProfile.role === 'superadmin' || realProfile.email === 'admin@ausarta.net') && isActuallyAusarta;

        if (canSpoof && (spoofedRole || spoofedEmpresa)) {
            // Need to fetch company data if spoofedEmpresa is set
            const getSpoofedCompany = async () => {
                let companyData = realProfile.empresas;
                if (spoofedEmpresa && spoofedEmpresa !== realProfile.empresa_id) {
                    const { data } = await supabase.from('empresas').select('*').eq('id', spoofedEmpresa).single();
                    if (data) companyData = data;
                }

                setProfile({
                    ...realProfile,
                    role: spoofedRole || realProfile.role,
                    empresa_id: spoofedEmpresa || realProfile.empresa_id,
                    empresas: companyData as Empresa | undefined
                });
            };
            getSpoofedCompany();
        } else {
            setProfile(realProfile);
        }
    }, [realProfile, spoofedRole, spoofedEmpresa]);

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

        // Special case: Superadmins always have full access
        if (profile.role === 'superadmin') return true;

        // Modules enabled for the company
        const companyModules = profile.empresas?.enabled_modules || [];
        const isModuleEnabled = companyModules.includes(module);

        // If it's the 'admin' module (User Management), regular users cannot access even if enabled for company
        if (module === 'admin' && profile.role === 'user') return false;

        // Default: modules must be enabled for the company
        // EXCEPT if there's an explicit manual permission override (like premium voice)
        const manualPerm = permissions.find(p => p.module === module);
        if (manualPerm) return manualPerm.enabled;

        return isModuleEnabled;
    };

    const isRole = (...roles: UserRole[]): boolean => {
        if (!profile) return false;
        return roles.includes(profile.role);
    };

    // Centralised Platform Management Check
    const isPlatformOwner = !!profile && profile.empresas?.nombre === 'Ausarta' && (profile.role === 'superadmin' || profile.role === 'admin');

    return (
        <AuthContext.Provider value={{
            user, session, profile, permissions, loading,
            signIn, signUp, signOut, hasPermission, isRole, refreshProfile,
            realProfile, isPlatformOwner, setSpoofedRole, setSpoofedEmpresa
        }}>
            {children}
        </AuthContext.Provider>
    );
};
