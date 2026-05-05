import React, { useState, useEffect } from 'react';
import {
    User, Mail, Building2, Shield, ShieldCheck, Save, Loader2,
    ArrowLeft, Briefcase, Calendar, CheckCircle, AlertTriangle
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { supabase } from '../lib/supabase';
import { useAuth } from '../contexts/AuthContext';
import type { UserProfile, UserRole, Empresa } from '../types';
import { toast } from 'react-hot-toast';

export const ProfileView: React.FC = () => {
    const { profile, realProfile, refreshProfile, setSpoofedRole, setSpoofedEmpresa } = useAuth();
    const { t } = useTranslation();

    // Original role/company to detect if they are "actually" a superadmin even if they switched
    // For now, let's assume if they have access to this view and were once superadmin, they can switch.
    // For now, let's assume if they have access to this view and were once superadmin, they can switch.
    // Use realProfile to check their actual privileges regardless of spoofing
    const actualProfile = realProfile || profile;
    const isRootEmail = actualProfile?.email === 'admin@ausarta.net';
    const canSwitch = actualProfile?.role === 'superadmin' || isRootEmail;

    const [loading, setLoading] = useState(false);
    const [saving, setSaving] = useState(false);
    const [empresas, setEmpresas] = useState<Empresa[]>([]);

    // Form state
    const [fullName, setFullName] = useState(profile?.full_name || '');
    const [position, setPosition] = useState(profile?.position || '');
    const [role, setRole] = useState<UserRole>(profile?.role || 'user');
    const [empresaId, setEmpresaId] = useState<number | null>(profile?.empresa_id || null);

    useEffect(() => {
        if (canSwitch) {
            loadEmpresas();
        }
    }, [canSwitch]);

    const loadEmpresas = async () => {
        setLoading(true);
        try {
            const API_URL = import.meta.env.VITE_API_URL || '';
            const res = await fetch(`${API_URL}/api/empresas`);
            if (res.ok) {
                const data = await res.json();
                setEmpresas(data);
            }
        } catch (err) {
            console.error('Error loading empresas:', err);
        } finally {
            setLoading(false);
        }
    };

    const handleSave = async () => {
        if (!profile) return;
        setSaving(true);
        try {
            // Only update personal details in DB
            const { error } = await supabase
                .from('user_profiles')
                .update({
                    full_name: fullName,
                    position: position,
                    updated_at: new Date().toISOString()
                })
                .eq('id', profile.id);

            if (error) throw error;

            // Apply Context Spoofing locally
            if (canSwitch) {
                // If they matched their actual role, we can remove spoof to save storage
                const updateRole = role === actualProfile?.role ? null : role;
                const updateEmpresa = empresaId === actualProfile?.empresa_id ? null : empresaId;

                setSpoofedRole(updateRole);
                setSpoofedEmpresa(updateEmpresa);
            }

            toast.success(t('Profile updated successfully'));
            await refreshProfile();
        } catch (err: any) {
            console.error('Error updating profile:', err);
            toast.error(`${t('Error updating profile')}: ${err.message}`);
        } finally {
            setSaving(false);
        }
    };

    if (!profile) return null;

    return (
        <div className="max-w-4xl mx-auto space-y-6 animate-in fade-in duration-500">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold text-gray-900 dark:text-white">{t('My Profile')}</h1>
                    <p className="text-gray-500 dark:text-gray-400 text-sm">{t('Manage your personal information and preferences')}</p>
                </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                {/* User Card */}
                <div className="md:col-span-1 space-y-6">
                    <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-100 dark:border-gray-700 shadow-sm overflow-hidden">
                        <div className="h-24 bg-gradient-to-r from-blue-600 to-indigo-600"></div>
                        <div className="px-6 pb-6 relative">
                            <div className="absolute -top-12 left-6">
                                <div className="w-24 h-24 rounded-2xl bg-white dark:bg-gray-800 p-1 shadow-lg">
                                    <div className="w-full h-full rounded-xl bg-gradient-to-br from-blue-400 to-blue-600 flex items-center justify-center text-white text-3xl font-bold">
                                        {profile.full_name?.charAt(0).toUpperCase() || profile.email.charAt(0).toUpperCase()}
                                    </div>
                                </div>
                            </div>
                            <div className="pt-14">
                                <h3 className="text-xl font-bold text-gray-900 dark:text-white">{profile.full_name || 'Usuario'}</h3>
                                <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">{profile.email}</p>

                                <div className="space-y-3">
                                    <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300">
                                        <div className="p-1.5 bg-gray-50 dark:bg-gray-700 rounded-lg">
                                            <Briefcase size={16} className="text-gray-400" />
                                        </div>
                                        <span>{profile.position || t('No Position')}</span>
                                    </div>
                                    <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300">
                                        <div className="p-1.5 bg-gray-50 dark:bg-gray-700 rounded-lg">
                                            {profile.role === 'superadmin' ? <ShieldCheck size={16} className="text-red-500" /> : profile.role === 'admin' ? <Shield size={16} className="text-blue-500" /> : <User size={16} />}
                                        </div>
                                        <span className="capitalize">{profile.role}</span>
                                    </div>
                                    <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300">
                                        <div className="p-1.5 bg-gray-50 dark:bg-gray-700 rounded-lg">
                                            <Building2 size={16} className="text-indigo-500" />
                                        </div>
                                        <span>{profile.empresas?.nombre || t('No Company')}</span>
                                    </div>
                                    <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300">
                                        <div className="p-1.5 bg-gray-50 dark:bg-gray-700 rounded-lg">
                                            <Calendar size={16} className="text-gray-400" />
                                        </div>
                                        <span>{t('Joined')}: {new Date(profile.created_at).toLocaleDateString()}</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    {profile.role === 'superadmin' && (
                        <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-100 dark:border-amber-800/50 p-4 rounded-xl flex gap-3">
                            <AlertTriangle className="text-amber-600 dark:text-amber-500 shrink-0" size={20} />
                            <p className="text-xs text-amber-700 dark:text-amber-400 leading-relaxed">
                                {t('As Superadmin, you can temporarily simulate other roles and companies. These changes only affect your local view and are not saved to the database.', 'Como Superadmin, puedes simular temporalmente otros roles y empresas. Estos cambios solo afectan a tu vista local y no se guardan en la base de datos.')}
                            </p>
                        </div>
                    )}
                </div>

                {/* Settings Form */}
                <div className="md:col-span-2 space-y-6">
                    <section className="bg-white dark:bg-gray-800 p-6 rounded-2xl border border-gray-100 dark:border-gray-700 shadow-sm space-y-6">
                        <div className="space-y-4">
                            <h4 className="text-lg font-bold text-gray-900 dark:text-white flex items-center gap-2 border-b border-gray-50 dark:border-gray-700 pb-3">
                                <User size={20} className="text-blue-500" />
                                {t('Account Settings')}
                            </h4>

                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div>
                                    <label className="block text-sm font-semibold text-gray-700 dark:text-gray-300 mb-1">{t('Full Name')}</label>
                                    <input
                                        type="text"
                                        value={fullName}
                                        onChange={(e) => setFullName(e.target.value)}
                                        className="w-full px-4 py-2.5 border border-gray-200 dark:border-gray-600 dark:bg-gray-700 rounded-xl focus:ring-2 focus:ring-blue-500/20 outline-none transition-all"
                                    />
                                </div>
                                <div>
                                    <label className="block text-sm font-semibold text-gray-700 dark:text-gray-300 mb-1">{t('Position')}</label>
                                    <input
                                        type="text"
                                        value={position}
                                        onChange={(e) => setPosition(e.target.value)}
                                        placeholder={t('e.g. CEO, Developer, Manager')}
                                        className="w-full px-4 py-2.5 border border-gray-200 dark:border-gray-600 dark:bg-gray-700 rounded-xl focus:ring-2 focus:ring-blue-500/20 outline-none transition-all"
                                    />
                                </div>
                                <div className="col-span-full">
                                    <label className="block text-sm font-semibold text-gray-700 dark:text-gray-300 mb-1">{t('Email Address')}</label>
                                    <input
                                        type="email"
                                        value={profile.email}
                                        disabled
                                        className="w-full px-4 py-2.5 bg-gray-50 dark:bg-gray-700/50 border border-gray-200 dark:border-gray-600 rounded-xl text-gray-500"
                                    />
                                    <p className="text-[10px] text-gray-400 mt-1">{t('Email cannot be changed')}</p>
                                </div>
                            </div>
                        </div>

                        {/* Superadmin Context Switcher */}
                        {canSwitch && (
                            <div className="space-y-4 pt-4 border-t border-gray-100 dark:border-gray-700">
                                <h4 className="text-lg font-bold text-gray-900 dark:text-white flex items-center gap-2">
                                    <ShieldCheck size={20} className="text-red-500" />
                                    {t('Developer / Context Mode')}
                                </h4>

                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 bg-gray-50 dark:bg-gray-900/50 p-4 rounded-xl border border-dotted border-gray-300 dark:border-gray-600">
                                    <div>
                                        <label className="block text-sm font-semibold text-gray-700 dark:text-gray-300 mb-1">{t('Simulation Role')}</label>
                                        <select
                                            value={role}
                                            onChange={(e) => setRole(e.target.value as UserRole)}
                                            className="w-full px-4 py-2.5 border border-gray-200 dark:border-gray-600 dark:bg-gray-700 rounded-xl focus:ring-2 focus:ring-blue-500/20 outline-none bg-white font-medium"
                                        >
                                            <option value="superadmin">Superadmin</option>
                                            <option value="admin">Admin</option>
                                            <option value="user">{t('User')}</option>
                                        </select>
                                    </div>
                                    <div>
                                        <label className="block text-sm font-semibold text-gray-700 dark:text-gray-300 mb-1">{t('Simulate Company')}</label>
                                        <select
                                            value={empresaId || ''}
                                            onChange={(e) => setEmpresaId(e.target.value === '' ? null : Number(e.target.value))}
                                            className="w-full px-4 py-2.5 border border-gray-200 dark:border-gray-600 dark:bg-gray-700 rounded-xl focus:ring-2 focus:ring-blue-500/20 outline-none bg-white font-medium"
                                        >
                                            <option value="">-- {t('No Company')} --</option>
                                            {empresas.map(emp => (
                                                <option key={emp.id} value={emp.id}>{emp.nombre}</option>
                                            ))}
                                        </select>
                                    </div>
                                    <div className="col-span-full">
                                        <p className="text-xs text-blue-500 font-medium italic">
                                            {t('Note: This is merely a UI simulation. You will still remain a Superadmin in the database. Reset to Superadmin to regain access to blocked panels.')}
                                        </p>
                                    </div>
                                </div>
                            </div>
                        )}

                        <div className="flex justify-end pt-4">
                            <button
                                onClick={handleSave}
                                disabled={saving}
                                className="flex items-center gap-2 px-8 py-3 bg-gradient-to-r from-blue-600 to-indigo-600 text-white rounded-xl hover:from-blue-500 hover:to-indigo-500 transition-all shadow-lg shadow-blue-500/20 font-bold"
                            >
                                {saving ? <Loader2 size={20} className="animate-spin" /> : <Save size={20} />}
                                {saving ? t('Saving...') : t('Save Profile')}
                            </button>
                        </div>
                    </section>
                </div>
            </div>
        </div>
    );
};

export default ProfileView;
