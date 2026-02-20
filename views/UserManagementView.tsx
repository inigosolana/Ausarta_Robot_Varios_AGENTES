import React, { useState, useEffect } from 'react';
import {
    Users, Plus, Shield, ShieldCheck, User, Trash2, Loader2,
    ToggleLeft, ToggleRight, X, Settings, ChevronDown, ChevronUp
} from 'lucide-react';
import { supabase } from '../lib/supabase';
import { useAuth } from '../contexts/AuthContext';
import type { UserProfile, UserPermission, UserRole } from '../types';
import { ALL_MODULES } from '../types';

const UserManagementView: React.FC = () => {
    const { profile: currentProfile, isRole } = useAuth();
    const [users, setUsers] = useState<(UserProfile & { permissions: UserPermission[] })[]>([]);
    const [loading, setLoading] = useState(true);
    const [showCreate, setShowCreate] = useState(false);
    const [expandedUser, setExpandedUser] = useState<string | null>(null);

    // Create user form
    const [newEmail, setNewEmail] = useState('');
    const [newPassword, setNewPassword] = useState('');
    const [newName, setNewName] = useState('');
    const [newRole, setNewRole] = useState<UserRole>('user');
    const [creating, setCreating] = useState(false);

    useEffect(() => {
        loadUsers();
    }, []);

    const loadUsers = async () => {
        setLoading(true);
        try {
            const { data: usersData, error } = await supabase
                .from('user_profiles')
                .select('*')
                .order('created_at', { ascending: false });

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
        if (!newEmail || !newPassword || !newName) {
            alert('Rellena todos los campos');
            return;
        }

        // Validate role permissions
        if (isRole('admin') && newRole !== 'user') {
            alert('Solo puedes crear usuarios con rol "user"');
            return;
        }
        if (isRole('superadmin') && newRole === 'superadmin') {
            alert('No puedes crear otro superadmin');
            return;
        }

        setCreating(true);
        try {
            // Sign up user via Supabase Auth
            const { data, error } = await supabase.auth.signUp({
                email: newEmail,
                password: newPassword,
                options: {
                    data: { full_name: newName, role: newRole }
                }
            });

            if (error) throw error;

            // If the trigger didn't fire or we need to update the role/creator
            if (data.user) {
                await supabase.from('user_profiles').upsert({
                    id: data.user.id,
                    email: newEmail,
                    full_name: newName,
                    role: newRole,
                    created_by: currentProfile?.id
                });

                // Set default permissions for new user (all enabled by default)
                const defaultPerms = ALL_MODULES.map(m => ({
                    user_id: data.user!.id,
                    module: m.key,
                    enabled: true,
                    granted_by: currentProfile?.id
                }));

                await supabase.from('user_permissions').insert(defaultPerms);
            }

            alert('Usuario creado correctamente');
            setShowCreate(false);
            setNewEmail('');
            setNewPassword('');
            setNewName('');
            setNewRole('user');
            loadUsers();
        } catch (err: any) {
            alert(`Error: ${err.message}`);
        } finally {
            setCreating(false);
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
            loadUsers();
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
        if (!confirm('¿Estás seguro de que quieres eliminar este usuario? Esta acción no se puede deshacer.')) return;
        try {
            await supabase.from('user_permissions').delete().eq('user_id', userId);
            await supabase.from('user_profiles').delete().eq('id', userId);
            setUsers(prev => prev.filter(u => u.id !== userId));
        } catch (err) {
            alert('Error al eliminar usuario');
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

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex justify-between items-center">
                <div>
                    <h1 className="text-2xl font-bold text-gray-900">Gestión de Usuarios</h1>
                    <p className="text-gray-500 text-sm">Administra roles y permisos</p>
                </div>
                <button
                    onClick={() => setShowCreate(true)}
                    className="flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-blue-600 to-blue-500 text-white rounded-xl hover:from-blue-500 hover:to-blue-400 transition-all shadow-lg shadow-blue-500/20 font-medium text-sm"
                >
                    <Plus size={18} />
                    Crear Usuario
                </button>
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
                            {expandedUser === user.id && user.role === 'user' && (
                                <div className="px-4 pb-4 border-t border-gray-100 pt-4">
                                    <div className="flex items-center gap-2 mb-3">
                                        <Settings size={14} className="text-gray-400" />
                                        <span className="text-sm font-medium text-gray-600">Módulos habilitados</span>
                                    </div>
                                    <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                                        {ALL_MODULES.map((mod) => {
                                            const perm = user.permissions.find(p => p.module === mod.key);
                                            const isEnabled = perm?.enabled ?? false;

                                            return (
                                                <button
                                                    key={mod.key}
                                                    onClick={() => canManageUser(user) && handleTogglePermission(user.id, mod.key, isEnabled)}
                                                    disabled={!canManageUser(user)}
                                                    className={`flex items-center gap-2 p-3 rounded-lg text-sm font-medium transition-all border ${isEnabled
                                                            ? 'bg-green-50 border-green-200 text-green-700 hover:bg-green-100'
                                                            : 'bg-gray-50 border-gray-200 text-gray-400 hover:bg-gray-100'
                                                        } ${!canManageUser(user) ? 'opacity-50 cursor-default' : 'cursor-pointer'}`}
                                                >
                                                    {isEnabled ? <ToggleRight size={16} className="text-green-500" /> : <ToggleLeft size={16} />}
                                                    {mod.label}
                                                </button>
                                            );
                                        })}
                                    </div>
                                </div>
                            )}

                            {expandedUser === user.id && user.role !== 'user' && (
                                <div className="px-4 pb-4 border-t border-gray-100 pt-4">
                                    <p className="text-sm text-gray-400 italic">Los administradores y superadmins tienen acceso a todos los módulos.</p>
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}

            {/* Create User Modal */}
            {showCreate && (
                <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
                    <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full overflow-hidden">
                        <div className="px-6 py-4 border-b border-gray-100 flex justify-between items-center bg-gray-50">
                            <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
                                <Users size={20} className="text-blue-600" /> Crear Usuario
                            </h3>
                            <button onClick={() => setShowCreate(false)} className="text-gray-400 hover:text-gray-600">
                                <X size={20} />
                            </button>
                        </div>

                        <div className="p-6 space-y-4">
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
                                <label className="block text-sm font-medium text-gray-700 mb-1">Contraseña</label>
                                <input
                                    type="password"
                                    value={newPassword}
                                    onChange={(e) => setNewPassword(e.target.value)}
                                    className="w-full px-4 py-2.5 border border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-500/20 outline-none"
                                    placeholder="Mínimo 6 caracteres"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Rol</label>
                                <select
                                    value={newRole}
                                    onChange={(e) => setNewRole(e.target.value as UserRole)}
                                    className="w-full px-4 py-2.5 border border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-500/20 outline-none bg-white"
                                >
                                    <option value="user">Usuario</option>
                                    {isRole('superadmin') && <option value="admin">Admin</option>}
                                </select>
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
                                {creating ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
                                {creating ? 'Creando...' : 'Crear Usuario'}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default UserManagementView;
