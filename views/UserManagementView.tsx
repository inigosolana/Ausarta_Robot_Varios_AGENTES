import React, { useState, useEffect } from 'react';
import {
    Users, Plus, Shield, ShieldCheck, User, Trash2, Loader2,
    ToggleLeft, ToggleRight, X, Settings, ChevronDown, ChevronUp,
    Mail, CheckCircle, AlertCircle
} from 'lucide-react';
import { supabase } from '../lib/supabase';
import { useAuth } from '../contexts/AuthContext';
import type { UserProfile, UserPermission, UserRole, Empresa } from '../types';
import { ALL_MODULES } from '../types';

const UserManagementView: React.FC = () => {
    const { profile: currentProfile, isRole } = useAuth();
    const [users, setUsers] = useState<(UserProfile & { permissions: UserPermission[], empresas?: Empresa | null })[]>([]);
    const [loading, setLoading] = useState(true);
    const [showCreate, setShowCreate] = useState(false);
    const [expandedUser, setExpandedUser] = useState<string | null>(null);
    const [empresas, setEmpresas] = useState<Empresa[]>([]);

    // Create user form
    const [newEmail, setNewEmail] = useState('');
    const [newName, setNewName] = useState('');
    const [newRole, setNewRole] = useState<UserRole>('user');
    const [newEmpresaId, setNewEmpresaId] = useState<number | ''>('');
    const [newPassword, setNewPassword] = useState('');
    const [creating, setCreating] = useState(false);
    const [inviteSuccess, setInviteSuccess] = useState(false);

    useEffect(() => {
        loadUsersAndEmpresas();
    }, []);

    const loadUsersAndEmpresas = async () => {
        setLoading(true);
        try {
            // 1. Load empresas based on role
            let empQuery = supabase.from('empresas').select('*').order('nombre');

            // Non-superadmins only see their own company
            if (!isRole('superadmin') && currentProfile?.empresa_id) {
                empQuery = empQuery.eq('id', currentProfile.empresa_id);
            }

            const { data: empData } = await empQuery;
            if (empData) setEmpresas(empData);

            // Pre-select empresa for admins
            if (isRole('admin') && !isRole('superadmin') && currentProfile?.empresa_id) {
                setNewEmpresaId(currentProfile.empresa_id);
            }

            // 2. Load user profiles based on role
            let userQuery = supabase
                .from('user_profiles')
                .select('*, empresas(*)')
                .order('created_at', { ascending: false });

            // Non-superadmins only see users from their own company
            if (!isRole('superadmin') && currentProfile?.empresa_id) {
                userQuery = userQuery.eq('empresa_id', currentProfile.empresa_id);
            }

            const { data: usersData, error } = await userQuery;
            if (error) throw error;

            const usersWithPerms = await Promise.all(
                (usersData || []).map(async (u: UserProfile) => {
                    const { data: perms } = await supabase
                        .from('user_permissions')
                        .select('*')
                        .eq('user_id', u.id);
                    return { ...u, permissions: (perms || []) as UserPermission[] };
                })
            );

            setUsers(usersWithPerms);
        } catch (err) {
            console.error('Error loading users:', err);
        } finally {
            setLoading(false);
        }
    };

    const handleCreateUser = async () => {
        if (!newEmail || !newName) {
            alert('Rellena nombre y email');
            return;
        }

        // Only superadmin and admin can create users
        if (!isRole('superadmin', 'admin')) {
            alert('No tienes permisos para crear usuarios');
            return;
        }

        // Admins can't create superadmins
        if (!isRole('superadmin') && newRole === 'superadmin') {
            alert('No puedes crear usuarios superadmin');
            return;
        }

        // Admins are locked to their company
        const finalEmpresaId = isRole('superadmin') ? newEmpresaId : currentProfile?.empresa_id;

        // Validate role permissions
        if (newRole === 'superadmin') {
            alert('No puedes crear otro superadmin');
            return;
        }

        setCreating(true);
        setInviteSuccess(false);
        try {
            // Generate a random temporary password if no explicitly provided password
            const generateRandomString = (length: number) => {
                const charset = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
                let retVal = "";
                if (window.crypto && window.crypto.getRandomValues) {
                    const values = new Uint32Array(length);
                    window.crypto.getRandomValues(values);
                    for (let i = 0; i < length; i++) {
                        retVal += charset.charAt(values[i] % charset.length);
                    }
                } else {
                    for (let i = 0; i < length; i++) {
                        retVal += charset.charAt(Math.floor(Math.random() * charset.length));
                    }
                }
                return retVal;
            };

            const API_URL = import.meta.env.VITE_API_URL || '';
            const tempPassword = newPassword || (generateRandomString(12) + '!Aa1');

            // Call Backend Proxy instead of n8n directly to avoid CORS issues
            const PROXY_URL = `${API_URL}/api/n8n/invite`;

            const res = await fetch(PROXY_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    email: newEmail,
                    password: tempPassword,
                    full_name: newName,
                    role: newRole,
                    empresa_id: finalEmpresaId || null
                })
            });


            if (!res.ok) {
                const errorText = await res.text();
                throw new Error(errorText || 'Error al conectar con n8n');
            }

            // The n8n workflow returns the Supabase response from the last node (or response node)
            const responseData = await res.json();
            // n8n might return results differently depending on the node, but usually Supabase Auth returns { id: "..." }
            // If the response node returns all data, we look for the ID.
            const newUserId = responseData.id || responseData[0]?.id || (responseData.json ? responseData.json.id : null);

            // Actualizar estado local (con el tipo correcto que incluye permisos)
            const newUser: UserProfile & { permissions: UserPermission[], empresas?: Empresa | null } = {
                id: newUserId,
                email: newEmail,
                full_name: newName,
                role: newRole,
                empresa_id: finalEmpresaId || null,
                permissions: [],
                is_active: true,
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
                created_by: currentProfile?.id || null,
                empresas: empresas.find(e => e.id === Number(finalEmpresaId)) || null
            };

            setUsers(prev => [newUser, ...prev]);
            setInviteSuccess(true);

            alert(`Usuario creado correctamente${!newPassword ? `. Contraseña temporal: ${tempPassword}` : ''}`);

            // Reset form and close
            setTimeout(() => {
                setShowCreate(false);
                setNewEmail('');
                setNewName('');
                setNewPassword('');
                setInviteSuccess(false);
                loadUsersAndEmpresas(); // Refrescar para traer permisos completos si el backend los creó
            }, 1000);

        } catch (err: any) {
            console.error("Error creating user:", err);
            alert(`Error: ${err.message}`);
        } finally {
            setCreating(false);
        }
    };

    const handleResendInvite = async (email: string) => {
        try {
            const { error } = await supabase.auth.resetPasswordForEmail(email, {
                redirectTo: window.location.origin.includes('localhost') ? 'https://app.ausarta.net' : window.location.origin,
            });
            if (error) throw error;
            alert(`📧 Email de invitación reenviado a ${email}`);
        } catch (err: any) {
            alert(`Error: ${err.message}`);
        }
    };

    const handleTogglePermission = async (userId: string, module: string, currentEnabled: boolean) => {
        try {
            const existing = users.find(u => u.id === userId)?.permissions.find(p => p.module === module);

            if (existing) {
                await supabase.from('user_permissions')
                    .update({ enabled: !currentEnabled })
                    .eq('user_id', userId)
                    .eq('module', module);
            } else {
                await supabase.from('user_permissions').insert({
                    user_id: userId,
                    module,
                    enabled: !currentEnabled,
                    granted_by: currentProfile?.id
                });
            }

            // Optimistic update
            setUsers(prev => prev.map(u => {
                if (u.id !== userId) return u;
                const existingPerm = u.permissions.find(p => p.module === module);
                if (existingPerm) {
                    return {
                        ...u,
                        permissions: u.permissions.map(p =>
                            p.module === module ? { ...p, enabled: !currentEnabled } : p
                        )
                    };
                } else {
                    return {
                        ...u,
                        permissions: [...u.permissions, {
                            id: Date.now(),
                            user_id: userId,
                            module,
                            enabled: !currentEnabled,
                            granted_by: currentProfile?.id || null,
                            created_at: new Date().toISOString()
                        }]
                    };
                }
            }));
        } catch (err) {
            alert('Error al cambiar permiso');
            loadUsersAndEmpresas();
        }
    };

    const handleToggleActive = async (userId: string, currentActive: boolean) => {
        try {
            await supabase.from('user_profiles')
                .update({ is_active: !currentActive })
                .eq('id', userId);

            setUsers(prev => prev.map(u =>
                u.id === userId ? { ...u, is_active: !currentActive } : u
            ));
        } catch (err) {
            alert('Error al cambiar estado del usuario');
        }
    };

    const handleDeleteUser = async (userId: string) => {
        if (!confirm('¿Estás seguro de que quieres eliminar este usuario? Esta acción no se puede deshacer y borrará también su acceso de autenticación.')) return;
        try {
            const API_URL = import.meta.env.VITE_API_URL || window.location.origin;
            const res = await fetch(`${API_URL}/api/admin/users/${userId}`, {
                method: 'DELETE'
            });

            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.error || 'Error al eliminar usuario');
            }

            setUsers(prev => prev.filter(u => u.id !== userId));
        } catch (err: any) {
            alert(`Error: ${err.message}`);
        }
    };

    const getRoleIcon = (role: UserRole) => {
        switch (role) {
            case 'superadmin': return <ShieldCheck size={16} className="text-red-500" />;
            case 'admin': return <Shield size={16} className="text-blue-500" />;
            default: return <User size={16} className="text-gray-500" />;
        }
    };

    const getRoleBadge = (role: UserRole) => {
        const colors: Record<UserRole, string> = {
            superadmin: 'bg-red-100 text-red-700',
            admin: 'bg-blue-100 text-blue-700',
            user: 'bg-gray-100 text-gray-700'
        };
        const labels: Record<UserRole, string> = {
            superadmin: 'Superadmin',
            admin: 'Admin',
            user: 'Usuario'
        };
        return (
            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${colors[role]}`}>
                {getRoleIcon(role)} {labels[role]}
            </span>
        );
    };

    const canManageUser = (targetUser: UserProfile): boolean => {
        if (!currentProfile) return false;
        if (currentProfile.id === targetUser.id) return false; // Can't manage self
        if (currentProfile.role === 'superadmin') return true;
        if (currentProfile.role === 'admin' && targetUser.role === 'user') return true;
        return false;
    };

    // Superadmins and Admins can create users
    const canCreateUsers = isRole('superadmin', 'admin');

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex justify-between items-center">
                <div>
                    <h1 className="text-2xl font-bold text-gray-900">Gestión de Usuarios</h1>
                    <p className="text-gray-500 text-sm">Administra roles y permisos</p>
                </div>
                {canCreateUsers && (
                    <button
                        onClick={() => setShowCreate(true)}
                        className="flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-blue-600 to-blue-500 text-white rounded-xl hover:from-blue-500 hover:to-blue-400 transition-all shadow-lg shadow-blue-500/20 font-medium text-sm"
                    >
                        <Plus size={18} />
                        Invitar Usuario
                    </button>
                )}
            </div>

            {/* Users Table / Cards */}
            {loading ? (
                <div className="flex justify-center py-20">
                    <Loader2 className="animate-spin text-gray-400" size={32} />
                </div>
            ) : (
                <div className="space-y-3">
                    {users.map((user) => (
                        <div key={user.id} className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
                            {/* User Row */}
                            <div
                                className="p-4 flex items-center justify-between cursor-pointer hover:bg-gray-50 transition-colors"
                                onClick={() => setExpandedUser(expandedUser === user.id ? null : user.id)}
                            >
                                <div className="flex items-center gap-4">
                                    <div className={`w-10 h-10 rounded-full flex items-center justify-center ${user.is_active ? 'bg-green-50' : 'bg-red-50'
                                        }`}>
                                        {getRoleIcon(user.role)}
                                    </div>
                                    <div>
                                        <div className="flex items-center gap-2">
                                            <h3 className="font-medium text-gray-900">{user.full_name || user.email}</h3>
                                            {getRoleBadge(user.role)}
                                            {user.empresas && (
                                                <span className="px-2 py-0.5 bg-indigo-50 text-indigo-700 rounded-full text-xs font-medium border border-indigo-100">
                                                    🏢 {user.empresas.nombre}
                                                </span>
                                            )}
                                            {!user.is_active && (
                                                <span className="px-2 py-0.5 bg-red-50 text-red-600 rounded-full text-xs font-medium">
                                                    Desactivado
                                                </span>
                                            )}
                                        </div>
                                        <p className="text-sm text-gray-400">{user.email}</p>
                                    </div>
                                </div>

                                <div className="flex items-center gap-2">
                                    {canManageUser(user) && (
                                        <>
                                            <button
                                                onClick={(e) => { e.stopPropagation(); handleResendInvite(user.email); }}
                                                className="p-1.5 rounded-lg hover:bg-blue-50 text-gray-400 hover:text-blue-600 transition-colors"
                                                title="Reenviar invitación / Reset contraseña"
                                            >
                                                <Mail size={16} />
                                            </button>
                                            <button
                                                onClick={(e) => { e.stopPropagation(); handleToggleActive(user.id, user.is_active); }}
                                                className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors"
                                                title={user.is_active ? 'Desactivar' : 'Activar'}
                                            >
                                                {user.is_active ? <ToggleRight size={20} className="text-green-500" /> : <ToggleLeft size={20} className="text-gray-400" />}
                                            </button>
                                            <button
                                                onClick={(e) => { e.stopPropagation(); handleDeleteUser(user.id); }}
                                                className="p-1.5 rounded-lg hover:bg-red-50 text-gray-400 hover:text-red-600 transition-colors"
                                                title="Eliminar"
                                            >
                                                <Trash2 size={16} />
                                            </button>
                                        </>
                                    )}
                                    {expandedUser === user.id ? <ChevronUp size={16} className="text-gray-400" /> : <ChevronDown size={16} className="text-gray-400" />}
                                </div>
                            </div>

                            {/* Expanded Permissions */}
                            {expandedUser === user.id && (
                                <div className="px-4 pb-4 border-t border-gray-100 pt-4">
                                    {(isRole('superadmin') || user.role === 'user') ? (
                                        <>
                                            <div className="flex items-center justify-between mb-3">
                                                <div className="flex items-center gap-2">
                                                    <Settings size={14} className="text-gray-400" />
                                                    <span className="text-sm font-medium text-gray-600">Permisos y Módulos</span>
                                                </div>
                                                {user.role !== 'user' && (
                                                    <span className="text-xs text-amber-600 font-medium bg-amber-50 px-2 py-0.5 rounded-full">
                                                        Admin: Acceso total exceptuando Premium
                                                    </span>
                                                )}
                                            </div>
                                            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                                                {ALL_MODULES.map((mod) => {
                                                    const perm = user.permissions.find(p => p.module === mod.key);
                                                    const isEnabled = perm?.enabled ?? false;

                                                    // For admins, non-premium modules are always enabled visually
                                                    const visuallyEnabled = (user.role !== 'user' && mod.key !== 'premium_voice') || isEnabled;

                                                    return (
                                                        <button
                                                            key={mod.key}
                                                            onClick={() => canManageUser(user) && handleTogglePermission(user.id, mod.key, isEnabled)}
                                                            disabled={!canManageUser(user) || (user.role !== 'user' && mod.key !== 'premium_voice')}
                                                            className={`flex items-center gap-2 p-3 rounded-lg text-sm font-medium transition-all border ${visuallyEnabled
                                                                ? 'bg-green-50 border-green-200 text-green-700 hover:bg-green-100'
                                                                : 'bg-gray-50 border-gray-200 text-gray-400 hover:bg-gray-100'
                                                                } ${(!canManageUser(user) || (user.role !== 'user' && mod.key !== 'premium_voice')) ? 'opacity-50 cursor-default' : 'cursor-pointer'}`}
                                                        >
                                                            {visuallyEnabled ? <ToggleRight size={16} className="text-green-500" /> : <ToggleLeft size={16} />}
                                                            {mod.label}
                                                        </button>
                                                    );
                                                })}
                                            </div>
                                        </>
                                    ) : (
                                        <div className="py-2">
                                            <p className="text-sm text-gray-400 italic">Los administradores tienen acceso a todos los módulos básicos.</p>
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}

            {/* Create / Invite User Modal */}
            {showCreate && (
                <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
                    <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full overflow-hidden">
                        <div className="px-6 py-4 border-b border-gray-100 flex justify-between items-center bg-gray-50">
                            <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
                                <Mail size={20} className="text-blue-600" /> Invitar Usuario
                            </h3>
                            <button onClick={() => { setShowCreate(false); setInviteSuccess(false); }} className="text-gray-400 hover:text-gray-600">
                                <X size={20} />
                            </button>
                        </div>

                        {inviteSuccess ? (
                            <div className="p-8 text-center">
                                <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-green-50 mb-4">
                                    <CheckCircle size={32} className="text-green-500" />
                                </div>
                                <h3 className="text-lg font-semibold text-gray-900 mb-2">¡Usuario creado con éxito!</h3>
                                <p className="text-gray-500 text-sm">
                                    {newPassword ? (
                                        <>El usuario ya puede acceder con el email <strong>{newEmail}</strong> y la contraseña proporcionada.</>
                                    ) : (
                                        <>Se ha enviado un email a <strong>{newEmail}</strong> con un enlace para crear su contraseña.</>
                                    )}
                                </p>
                            </div>
                        ) : (
                            <>
                                <div className="p-6 space-y-4">
                                    {/* Info banner */}
                                    <div className="flex items-start gap-3 p-3 bg-blue-50 border border-blue-100 rounded-xl">
                                        <AlertCircle size={18} className="text-blue-500 mt-0.5 shrink-0" />
                                        <p className="text-sm text-blue-700">
                                            Puedes asignarle una contraseña directamente, o dejarlo en blanco para que reciba un email y cree la suya.
                                        </p>
                                    </div>

                                    <div>
                                        <label className="block text-sm font-medium text-gray-700 mb-1">Nombre completo</label>
                                        <input
                                            type="text"
                                            value={newName}
                                            onChange={(e) => setNewName(e.target.value)}
                                            className="w-full px-4 py-2.5 border border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-500/20 outline-none"
                                            placeholder="Juan Pérez"
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
                                        <input
                                            type="email"
                                            value={newEmail}
                                            onChange={(e) => setNewEmail(e.target.value)}
                                            className="w-full px-4 py-2.5 border border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-500/20 outline-none"
                                            placeholder="juan@empresa.com"
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-gray-700 mb-1">Rol</label>
                                        <select
                                            value={newRole}
                                            onChange={(e) => setNewRole(e.target.value as UserRole)}
                                            className="w-full px-4 py-2.5 border border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-500/20 outline-none bg-white font-medium"
                                        >
                                            {isRole('superadmin') && <option value="superadmin">Superadmin</option>}
                                            <option value="admin">Admin (Empresa)</option>
                                            <option value="user">Usuario (Solo Resultados)</option>
                                        </select>
                                    </div>
                                    {isRole('superadmin') ? (
                                        <div>
                                            <label className="block text-sm font-medium text-gray-700 mb-1">Empresa</label>
                                            <select
                                                value={newEmpresaId}
                                                onChange={(e) => setNewEmpresaId(e.target.value === '' ? '' : Number(e.target.value))}
                                                className="w-full px-4 py-2.5 border border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-500/20 outline-none bg-white font-medium"
                                            >
                                                <option value="">-- Ninguna --</option>
                                                {empresas.map(emp => (
                                                    <option key={emp.id} value={emp.id}>{emp.nombre}</option>
                                                ))}
                                            </select>
                                        </div>
                                    ) : (
                                        <div>
                                            <label className="block text-sm font-medium text-gray-700 mb-1">Empresa</label>
                                            <div className="px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-gray-600 font-medium">
                                                {empresas.find(e => e.id === currentProfile?.empresa_id)?.nombre || 'Tu Empresa'}
                                            </div>
                                        </div>
                                    )}

                                    <div className="pt-2 border-t border-gray-100 mt-2">
                                        <label className="block text-sm font-medium text-gray-700 mb-1">
                                            Contraseña <span className="text-gray-400 font-normal">(Opcional)</span>
                                        </label>
                                        <input
                                            type="text"
                                            value={newPassword}
                                            onChange={(e) => setNewPassword(e.target.value)}
                                            className="w-full px-4 py-2.5 border border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-500/20 outline-none"
                                            placeholder="Introduce una contraseña para el usuario"
                                        />
                                        <p className="text-xs text-gray-500 mt-1.5">Si lo dejas en blanco, enviaremos un email de invitación. (Mínimo 6 caracteres)</p>
                                    </div>
                                </div>

                                <div className="px-6 py-4 bg-gray-50 border-t border-gray-100 flex justify-end gap-3">
                                    <button onClick={() => setShowCreate(false)} className="px-4 py-2 text-gray-700 hover:bg-gray-100 rounded-lg transition-colors">
                                        Cancelar
                                    </button>
                                    <button
                                        onClick={handleCreateUser}
                                        disabled={creating}
                                        className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-500 disabled:opacity-50 flex items-center gap-2 transition-colors"
                                    >
                                        {creating ? <Loader2 size={16} className="animate-spin" /> : <Mail size={16} />}
                                        {creating ? 'Enviando...' : 'Enviar invitación'}
                                    </button>
                                </div>
                            </>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
};

export default UserManagementView;
