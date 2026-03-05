import React, { useState, useEffect } from 'react';
import {
    Users, Plus, Shield, ShieldCheck, User, Trash2, Loader2,
    ToggleLeft, ToggleRight, X, Settings, ChevronDown, ChevronUp,
    Mail, CheckCircle, AlertCircle
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { supabase } from '../lib/supabase';
import { useAuth } from '../contexts/AuthContext';
import type { UserProfile, UserPermission, UserRole, Empresa } from '../types';
import { ALL_MODULES } from '../types';

const SkeletonRow = () => (
    <div className="flex items-center gap-4 p-4 border-b border-gray-100 animate-pulse">
        <div className="w-10 h-10 rounded-full bg-gray-200" />
        <div className="flex-1 space-y-2">
            <div className="h-4 bg-gray-200 rounded w-1/4" />
            <div className="h-3 bg-gray-100 rounded w-1/3" />
        </div>
        <div className="w-20 h-6 bg-gray-100 rounded-full" />
        <div className="w-32 h-6 bg-gray-100 rounded-full" />
        <div className="w-8 h-8 rounded-lg bg-gray-100" />
    </div>
);

const UserManagementView: React.FC = () => {
    const { profile: currentProfile, isRole, isPlatformOwner } = useAuth();
    const { t } = useTranslation();

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
            // 1. Load empresas using API (Cache-friendly)
            const empRes = await fetch(`${process.env.REACT_APP_API_URL || ''}/api/empresas`);
            const empData = await empRes.json();

            if (Array.isArray(empData)) {
                let filteredEmp = empData;
                if (!isPlatformOwner && currentProfile?.empresa_id) {
                    filteredEmp = empData.filter(e => e.id === currentProfile.empresa_id);
                }
                setEmpresas(filteredEmp);
            }

            // 2. Load user profiles using API (Cache-friendly)
            const userRes = await fetch(`${process.env.REACT_APP_API_URL || ''}/api/users`);
            const usersData = await userRes.json();

            if (Array.isArray(usersData)) {
                let filteredUsers = usersData;
                if (!isPlatformOwner && currentProfile?.empresa_id) {
                    filteredUsers = usersData.filter(u => u.empresa_id === currentProfile.empresa_id);
                }

                // Enrichment still needed for current profile details unless backend does it
                // But the API already does `select("*, empresas(*)")`
                const usersWithPerms = await Promise.all(
                    filteredUsers.map(async (u: any) => {
                        const { data: perms } = await supabase
                            .from('user_permissions')
                            .select('*')
                            .eq('user_id', u.id);
                        return { ...u, permissions: (perms || []) as UserPermission[] };
                    })
                );
                setUsers(usersWithPerms);
            }
        } catch (err) {
            console.error('Error loading users:', err);
        } finally {
            setTimeout(() => setLoading(false), 300); // Small delay for smooth transition
        }
    };

    const handleCreateUser = async () => {
        if (!newEmail || !newName) {
            alert(t('Fill in name and email', 'Rellena nombre y email'));
            return;
        }

        // Only superadmin and admin can create users
        if (!isRole('superadmin', 'admin')) {
            alert(t('You do not have permissions to create users', 'No tienes permisos para crear usuarios'));
            return;
        }

        // Admins can't create superadmins
        if (!isRole('superadmin') && newRole === 'superadmin') {
            alert(t('You cannot create superadmin users', 'No puedes crear usuarios superadmin'));
            return;
        }

        // AUSARTA PROTECTION: Admins of Ausarta cannot create users IN Ausarta
        const selectedEmpresa = empresas.find(e => e.id === Number(newEmpresaId));
        if (currentProfile?.empresas?.nombre === 'Ausarta' && currentProfile?.role === 'admin' && selectedEmpresa?.nombre === 'Ausarta') {
            alert(t('As an administrator, you cannot create users within the Ausarta company. This action is reserved for Superadmins.', 'Como administrador, no puedes crear usuarios dentro de la empresa Ausarta. Esta acción está reservada para Superadmins.'));
            return;
        }

        // Admins are locked to their company unless platform owner
        const finalEmpresaId = isPlatformOwner ? newEmpresaId : currentProfile?.empresa_id;

        // Check admin limit if newRole is admin
        if (newRole === 'admin') {
            const selectedEmpresa = empresas.find(e => e.id === Number(finalEmpresaId));
            // Ausarta (ID 1 usually, but check by name) can have many admins
            if (selectedEmpresa && selectedEmpresa.nombre !== 'Ausarta') {
                const existingAdmins = users.filter(u => u.empresa_id === selectedEmpresa.id && u.role === 'admin').length;
                const limit = selectedEmpresa.max_admins || 1;
                if (existingAdmins >= limit) {
                    alert(t('This company already has the maximum allowed administrators ({{limit}}). To add more, the main administrator must enable it (Premium Service).', 'Esta empresa ya tiene el máximo permitido de administradores ({{limit}}). Para añadir más, el administrador principal debe habilitarlo (Servicio Premium).', { limit }));
                    return;
                }
            }
        }

        setCreating(true);
        setInviteSuccess(false);
        try {
            const API_URL = import.meta.env.VITE_API_URL || '';
            const ADMIN_URL = `${API_URL}/api/admin/users`;

            const res = await fetch(ADMIN_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    email: newEmail,
                    password: newPassword || '',
                    full_name: newName,
                    role: newRole,
                    empresa_id: finalEmpresaId || null,
                    redirect_to: window.location.origin.includes('localhost') ? 'https://app.ausarta.net' : window.location.origin
                })
            });


            if (!res.ok) {
                const text = await res.text();
                try {
                    const parsed = JSON.parse(text);
                    throw new Error(parsed.message || parsed.error || text);
                } catch {
                    throw new Error(text || t('Error creating user', 'Error al crear el usuario'));
                }
            }

            const responseData = await res.json();
            const newUserId = responseData.user_id;
            const invited = Boolean(responseData.invited);

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

            if (invited) {
                alert(t('Invitation email sent successfully!', '¡Email de invitación enviado correctamente!'));
            } else {
                alert(t('User created correctly', 'Usuario creado correctamente'));
            }

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
            alert(`📧 ${t('Invitation email resent to', 'Email de invitación reenviado a')} ${email}`);
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
            alert(t('Error changing permission', 'Error al cambiar permiso'));
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
            alert(t('Error changing user status', 'Error al cambiar estado del usuario'));
        }
    };

    const handleDeleteUser = async (userId: string) => {
        if (!confirm(t('Are you sure you want to delete this user? This action cannot be undone and will also delete their authentication access.', '¿Estás seguro de que quieres eliminar este usuario? Esta acción no se puede deshacer y borrará también su acceso de autenticación.'))) return;
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
            user: t('User', 'Usuario')
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

        // AUSARTA PROTECTION: Admins of Ausarta (even if platform owners) 
        // CANNOT manage users of the Ausarta company (ID 1/Nombre Ausarta)
        if (targetUser.empresas?.nombre === 'Ausarta' && currentProfile.role === 'admin') {
            return false;
        }

        if (currentProfile.role === 'superadmin') return true;

        // Admins can manage regular users of their own company
        if (currentProfile.role === 'admin' && targetUser.role === 'user') {
            return currentProfile.empresa_id === targetUser.empresa_id;
        }

        return false;
    };

    // Superadmins and Admins can create users
    const canCreateUsers = isRole('superadmin', 'admin');

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex justify-between items-center">
                <div>
                    <h1 className="text-2xl font-bold text-gray-900">{t('User Management', 'Gestión de Usuarios')}</h1>
                    <p className="text-gray-500 text-sm">{t('Manage roles and permissions', 'Administra roles y permisos')}</p>
                </div>
                {canCreateUsers && (
                    <button
                        onClick={() => setShowCreate(true)}
                        className="flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-blue-600 to-blue-500 text-white rounded-xl hover:from-blue-500 hover:to-blue-400 transition-all shadow-lg shadow-blue-500/20 font-medium text-sm"
                    >
                        <Plus size={18} />
                        {t('Invite User', 'Invitar Usuario')}
                    </button>
                )}
            </div>

            {/* Users Table / Cards */}
            <div className="space-y-3">
                {loading ? (
                    <>
                        {[1, 2, 3, 4, 5].map(i => <SkeletonRow key={i} />)}
                    </>
                ) : users.length === 0 ? (
                    <div className="p-12 text-center bg-white rounded-xl border border-gray-100 shadow-sm">
                        <div className="w-16 h-16 bg-gray-50 rounded-full flex items-center justify-center mx-auto mb-4">
                            <Users size={32} className="text-gray-300" />
                        </div>
                        <p className="text-gray-500 font-medium">{t('No users found', 'No se encontraron usuarios')}</p>
                    </div>
                ) : (
                    users.map((user) => (
                        <div key={user.id} className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden animate-in fade-in slide-in-from-bottom-2 duration-300">
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
                                                    {t('Disabled', 'Desactivado')}
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
                                                title={t('Resend invitation / Reset password', 'Reenviar invitación / Reset contraseña')}
                                            >
                                                <Mail size={16} />
                                            </button>
                                            <button
                                                onClick={(e) => { e.stopPropagation(); handleToggleActive(user.id, user.is_active); }}
                                                className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors"
                                                title={user.is_active ? t('Deactivate', 'Desactivar') : t('Activate', 'Activar')}
                                            >
                                                {user.is_active ? <ToggleRight size={20} className="text-green-500" /> : <ToggleLeft size={20} className="text-gray-400" />}
                                            </button>
                                            <button
                                                onClick={(e) => { e.stopPropagation(); handleDeleteUser(user.id); }}
                                                className="p-1.5 rounded-lg hover:bg-red-50 text-gray-400 hover:text-red-600 transition-colors"
                                                title={t('Delete', 'Eliminar')}
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
                                    {(isPlatformOwner || user.role === 'user') ? (
                                        <>
                                            <div className="flex items-center justify-between mb-3">
                                                <div className="flex items-center gap-2">
                                                    <Settings size={14} className="text-gray-400" />
                                                    <span className="text-sm font-medium text-gray-600">{t('Permissions and Modules', 'Permisos y Módulos')}</span>
                                                </div>
                                                {user.role !== 'user' && (
                                                    <span className="text-xs text-amber-600 font-medium bg-amber-50 px-2 py-0.5 rounded-full">
                                                        {t('Admin: Total access except Premium', 'Admin: Acceso total exceptuando Premium')}
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
                                            <p className="text-sm text-gray-400 italic">{t('Administrators have access to all basic modules.', 'Los administradores tienen acceso a todos los módulos básicos.')}</p>
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    ))
                )}
            </div>

            {/* Create / Invite User Modal */}
            {showCreate && (
                <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
                    <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full overflow-hidden">
                        <div className="px-6 py-4 border-b border-gray-100 flex justify-between items-center bg-gray-50">
                            <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
                                <Mail size={20} className="text-blue-600" /> {t('Invite User', 'Invitar Usuario')}
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
                                <h3 className="text-lg font-semibold text-gray-900 mb-2">{t('User created successfully!', '¡Usuario creado con éxito!')}</h3>
                                <p className="text-gray-500 text-sm">
                                    {newPassword ? (
                                        <>{t('The user can now log in with the email {{email}} and the provided password.', 'El usuario ya puede acceder con el email <strong>{{email}}</strong> y la contraseña proporcionada.', { email: newEmail })}</>
                                    ) : (
                                        <>{t('An email has been sent to {{email}} with a link to create their password.', 'Se ha enviado un email a <strong>{{email}}</strong> con un enlace para crear su contraseña.', { email: newEmail })}</>
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
                                            {t('You can assign a password directly, or leave it blank to receive an email and create theirs.', 'Puedes asignarle una contraseña directamente, o dejarlo en blanco para que reciba un email y cree la suya.')}
                                        </p>
                                    </div>

                                    <div>
                                        <label className="block text-sm font-medium text-gray-700 mb-1">{t('Full Name', 'Nombre completo')}</label>
                                        <input
                                            type="text"
                                            value={newName}
                                            onChange={(e) => setNewName(e.target.value)}
                                            className="w-full px-4 py-2.5 border border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-500/20 outline-none"
                                            placeholder="Juan Pérez"
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-gray-700 mb-1">{t('Email', 'Email')}</label>
                                        <input
                                            type="email"
                                            value={newEmail}
                                            onChange={(e) => setNewEmail(e.target.value)}
                                            className="w-full px-4 py-2.5 border border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-500/20 outline-none"
                                            placeholder="juan@empresa.com"
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-gray-700 mb-1">{t('Role', 'Rol')}</label>
                                        <select
                                            value={newRole}
                                            onChange={(e) => setNewRole(e.target.value as UserRole)}
                                            className="w-full px-4 py-2.5 border border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-500/20 outline-none bg-white font-medium"
                                        >
                                            {isRole('superadmin') && <option value="superadmin">Superadmin</option>}
                                            <option value="admin">{t('Admin (Company)', 'Admin (Empresa)')}</option>
                                            <option value="user">{t('User (Results Only)', 'Usuario (Solo Resultados)')}</option>
                                        </select>
                                    </div>
                                    {isPlatformOwner ? (
                                        <div>
                                            <label className="block text-sm font-medium text-gray-700 mb-1">{t('Company', 'Empresa')}</label>
                                            <select
                                                value={newEmpresaId}
                                                onChange={(e) => setNewEmpresaId(e.target.value === '' ? '' : Number(e.target.value))}
                                                className="w-full px-4 py-2.5 border border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-500/20 outline-none bg-white font-medium"
                                            >
                                                <option value="">-- {t('None', 'Ninguna')} --</option>
                                                {empresas
                                                    .filter(emp => !(currentProfile?.role === 'admin' && emp.nombre === 'Ausarta'))
                                                    .map(emp => (
                                                        <option key={emp.id} value={emp.id}>{emp.nombre}</option>
                                                    ))}
                                            </select>
                                        </div>
                                    ) : (
                                        <div>
                                            <label className="block text-sm font-medium text-gray-700 mb-1">{t('Company', 'Empresa')}</label>
                                            <div className="px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-gray-600 font-medium">
                                                {empresas.find(e => e.id === currentProfile?.empresa_id)?.nombre || t('Your Company', 'Tu Empresa')}
                                            </div>
                                        </div>
                                    )}

                                    <div className="pt-2 border-t border-gray-100 mt-2">
                                        <label className="block text-sm font-medium text-gray-700 mb-1">
                                            {t('Password', 'Contraseña')} <span className="text-gray-400 font-normal">({t('Optional', 'Opcional')})</span>
                                        </label>
                                        <input
                                            type="text"
                                            value={newPassword}
                                            onChange={(e) => setNewPassword(e.target.value)}
                                            className="w-full px-4 py-2.5 border border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-500/20 outline-none"
                                            placeholder={t('Enter a password for the user', 'Introduce una contraseña para el usuario')}
                                        />
                                        <p className="text-xs text-gray-500 mt-1.5">{t('If you leave it blank, we will send an invitation email. (Minimum 6 characters)', 'Si lo dejas en blanco, enviaremos un email de invitación. (Mínimo 6 caracteres)')}</p>
                                    </div>
                                </div>

                                <div className="px-6 py-4 bg-gray-50 border-t border-gray-100 flex justify-end gap-3">
                                    <button onClick={() => setShowCreate(false)} className="px-4 py-2 text-gray-700 hover:bg-gray-100 rounded-lg transition-colors">
                                        {t('Cancel', 'Cancelar')}
                                    </button>
                                    <button
                                        onClick={handleCreateUser}
                                        disabled={creating}
                                        className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-500 disabled:opacity-50 flex items-center gap-2 transition-colors"
                                    >
                                        {creating ? <Loader2 size={16} className="animate-spin" /> : <Mail size={16} />}
                                        {creating ? t('Sending...', 'Enviando...') : t('Send invitation', 'Enviar invitación')}
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
