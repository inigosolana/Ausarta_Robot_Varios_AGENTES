import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { supabase } from '../lib/supabase';
import { canUseSimulationMode, isAusartaEmpresa } from '../lib/platformAccess';
import { clearSessionAuth, setImpersonateToken as storeImpersonateToken } from '../lib/sessionAuthStore';
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
    /** Superadmin o admin de empresa Ausarta: acceso global a datos */
    hasGlobalAccess: boolean;
    /** Solo superadmin: crear administradores de la empresa Ausarta */
    canCreateAusartaAdmins: boolean;
    setSpoofedRole: (role: UserRole | null) => void;
    setSpoofedEmpresa: (empresaId: number | null) => void;
    setImpersonateToken: (token: string | null) => void;
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

    // Simulación de rol/empresa: sessionStorage (se limpia al cerrar pestaña)
    const [spoofedRole, setSpoofedRoleState] = useState<UserRole | null>(() => {
        return (sessionStorage.getItem('spoofedRole') as UserRole) || null;
    });
    const [spoofedEmpresa, setSpoofedEmpresaState] = useState<number | null>(() => {
        const val = sessionStorage.getItem('spoofedEmpresa');
        return val ? Number(val) : null;
    });

    const setSpoofedRole = (role: UserRole | null) => {
        if (role) sessionStorage.setItem('spoofedRole', role);
        else sessionStorage.removeItem('spoofedRole');
        setSpoofedRoleState(role);
    };

    const setSpoofedEmpresa = (empresaId: number | null) => {
        if (empresaId) sessionStorage.setItem('spoofedEmpresa', empresaId.toString());
        else sessionStorage.removeItem('spoofedEmpresa');
        setSpoofedEmpresaState(empresaId);
    };

    const setImpersonateToken = (token: string | null) => {
        storeImpersonateToken(token);
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

        const canSpoof = canUseSimulationMode(realProfile);

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
        localStorage.removeItem('impersonateToken');
        localStorage.removeItem('spoofedRole');
        localStorage.removeItem('spoofedEmpresa');
    }, []);

    useEffect(() => {
        let cancelled = false;

        const finishLoading = () => {
            if (!cancelled) setLoading(false);
        };

        const timeout = window.setTimeout(() => {
            console.warn('Auth: timeout esperando sesión de Supabase');
            finishLoading();
        }, 10000);

        supabase.auth.getSession()
            .then(({ data: { session: s } }) => {
                if (cancelled) return;
                setSession(s);
                setUser(s?.user ?? null);
                if (s?.user) {
                    loadUserData(s.user.id).finally(finishLoading);
                } else {
                    finishLoading();
                }
            })
            .catch((err) => {
                console.error('Auth: error al obtener sesión', err);
                finishLoading();
            })
            .finally(() => window.clearTimeout(timeout));

        // No usar async/await aquí: bloquea el lock interno de Supabase Auth
        // y hace que updateUser() se quede colgado durante el recovery.
        const { data: { subscription } } = supabase.auth.onAuthStateChange(
            (_event, s) => {
                setSession(s);
                setUser(s?.user ?? null);
                if (s?.user) {
                    setTimeout(() => {
                        void loadUserData(s.user.id);
                    }, 0);
                } else {
                    setProfile(null);
                    setPermissions([]);
                }
            }
        );

        return () => {
            cancelled = true;
            window.clearTimeout(timeout);
            subscription.unsubscribe();
        };
    }, []);

    const signIn = async (email: string, password: string) => {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        return { error: error as Error | null };
    };

    const signUp = async (email: string, password: string, fullName: string, _role?: UserRole) => {
        const { error } = await supabase.auth.signUp({
            email,
            password,
            options: {
                data: { full_name: fullName }
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
        setSpoofedRole(null);
        setSpoofedEmpresa(null);
        clearSessionAuth();
    };

    const hasPermission = (module: string): boolean => {
        if (!profile) return false;

        // Superadmin y admin de Ausarta: acceso completo a módulos (misma visibilidad de datos)
        const isAusartaAdmin =
            profile.role === 'admin' && isAusartaEmpresa(profile);
        if (profile.role === 'superadmin' || isAusartaAdmin) return true;

        // Modules enabled for the company
        const companyModules = profile.empresas?.enabled_modules || [];
        const isModuleEnabled = companyModules.includes(module);

        // If it's the 'admin' module (User Management), regular users cannot access even if enabled for company
        if (module === 'admin' && profile.role === 'user') return false;

        // Default: modules must be enabled for the company
        // EXCEPT if there's an explicit manual permission override (like premium voice)
        const manualPerm = permissions.find(p => p.module === module);

        // Strict restriction for 'Usage' module: Only for platform owners (Ausarta Admin/Super)
        if (module === 'usage') {
            return profile.role === 'superadmin' || (profile.role === 'admin' && profile.empresas?.nombre === 'Ausarta');
        }

        if (manualPerm) return manualPerm.enabled;

        return isModuleEnabled;
    };

    const isRole = (...roles: UserRole[]): boolean => {
        if (!profile) return false;
        return roles.includes(profile.role);
    };

    // Plataforma Ausarta: admin de empresa Ausarta o superadmin
    const isPlatformOwner =
        !!profile &&
        isAusartaEmpresa(profile) &&
        (profile.role === 'superadmin' || profile.role === 'admin');

    const hasGlobalAccess = isPlatformOwner;
    const canCreateAusartaAdmins = profile?.role === 'superadmin';

    return (
        <AuthContext.Provider value={{
            user, session, profile, permissions, loading,
            signIn, signUp, signOut, hasPermission, isRole, refreshProfile,
            realProfile, isPlatformOwner, hasGlobalAccess, canCreateAusartaAdmins,
            setSpoofedRole, setSpoofedEmpresa, setImpersonateToken
        }}>
            {children}
        </AuthContext.Provider>
    );
};
