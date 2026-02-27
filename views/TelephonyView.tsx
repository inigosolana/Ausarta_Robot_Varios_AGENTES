import React from 'react';
import { ChevronDown, AlertTriangle, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

const TelephonyView: React.FC = () => {
  const { t } = useTranslation();
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-gray-900">{t('Telephony Configuration', 'Configuración de Telefonía')}</h1>
        <p className="text-gray-500 text-sm mt-1">{t('Configure your telephony provider for outbound calls.', 'Configura tu proveedor de telefonía para llamadas salientes.')}</p>
      </header>

      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-8 space-y-6">
        <div>
          <label className="block text-sm font-semibold text-gray-800 mb-2">{t('Telephony Provider', 'Proveedor de Telefonía')}</label>
          <div className="relative">
            <select className="w-full h-10 px-4 pr-10 appearance-none bg-white border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-500 transition-all cursor-pointer">
              <option>LCR (Generic SIP / Asterisk)</option>
            </select>
            <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" size={16} />
          </div>
        </div>

        <div className="bg-gray-50/50 rounded-lg p-4 border border-gray-100">
          <h3 className="text-sm font-semibold text-gray-800 mb-1">{t('LCR Configuration', 'Configuración LCR')}</h3>
          <p className="text-xs text-gray-500 leading-relaxed">
            {t('Using local Asterisk/LCR trunk. No additional credentials required here. Ensure your docker-compose is configured with proper Asterisk/ARI environment variables.', 'Usando el troncal local Asterisk/LCR. No se requieren credenciales adicionales aquí. Asegúrate de que tu docker-compose esté configurado con las variables de entorno de Asterisk/ARI adecuadas.')}
          </p>
        </div>

        <div>
          <label className="block text-sm font-semibold text-gray-800 mb-2">{t('From Numbers (Comma separated)', 'Números de Origen (Separados por coma)')}</label>
          <input
            type="text"
            placeholder={t('e.g. +34944771453, +34988...', 'ej: +34944771453, +34988...')}
            className="w-full h-10 px-4 bg-white border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-500 transition-all"
          />
          <p className="text-[11px] text-gray-400 mt-2">{t('Numbers that will appear as Caller ID.', 'Números que aparecerán como identificador de llamada (Caller ID).')}</p>
        </div>

        <div className="flex justify-end pt-4">
          <button className="px-6 py-2.5 bg-[#121212] text-white text-sm font-medium rounded-lg hover:bg-black transition-colors shadow-sm">
            {t('Save Configuration', 'Guardar Configuración')}
          </button>
        </div>
      </div>

      <div className="bg-red-50 rounded-xl border border-red-100 p-8 space-y-4">
        <div>
          <h3 className="text-sm font-bold text-red-800 flex items-center gap-2">
            <AlertTriangle size={18} />
            {t('System Maintenance', 'Mantenimiento del Sistema')}
          </h3>
          <p className="text-xs text-red-600 mt-1 uppercase tracking-wider font-bold opacity-70">{t('Extreme Cleanup', 'Limpieza Extrema')}</p>
        </div>
        <p className="text-sm text-red-700">
          {t('If the system hangs with the message "Calls in progress" and the agent does not respond, you can force the cleanup of all active rooms. This will hang up all current calls.', 'Si el sistema se queda bloqueado con el mensaje <strong>"Hay llamadas en curso"</strong> y el agente no responde, puedes forzar la limpieza de todas las salas activas. Esto colgará todas las llamadas actuales.')}
        </p>
        <div className="flex justify-start">
          <button
            onClick={async () => {
              if (window.confirm(t('Are you sure you want to force close ALL active calls? This will unlock the system.', '¿Estás seguro de que quieres forzar el cierre de TODAS las llamadas activas? Esto desbloqueará el sistema.'))) {
                try {
                  const res = await fetch(`${import.meta.env.VITE_API_URL || '/api'}/calls/cleanup`, { method: 'POST' });
                  if (res.ok) alert(t('✅ System cleaned successfully. All rooms have been cleared.', '✅ Sistema limpiado correctamente. Todas las salas han sido borradas.'));
                  else alert(t('❌ Error cleaning the rooms.', '❌ Error al limpiar las salas.'));
                } catch (e) {
                  alert(t('Server connection error.', 'Error de conexión con el servidor.'));
                }
              }
            }}
            className="flex items-center gap-2 px-6 py-2.5 bg-red-600 text-white text-sm font-bold rounded-lg hover:bg-red-700 transition-colors shadow-sm"
          >
            <Trash2 size={18} />
            {t('Reset Rooms and Unlock System', 'Resetear Salas y Desbloquear Sistema')}
          </button>
        </div>
      </div>
    </div>
  );
};

export default TelephonyView;
