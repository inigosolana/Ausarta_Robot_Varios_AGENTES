/**
 * AgentTemplateGallery — Galería de plantillas para crear un agente rápidamente.
 *
 * Se muestra como modal cuando el usuario pulsa "Crear Agente".
 * Cada plantilla pre-carga nombre, instrucciones, saludo y extraction_schema.
 * La última opción ("Desde cero") abre el formulario vacío como antes.
 */

import React, { useState } from 'react';
import { X, ChevronRight, Sparkles } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { AgentConfig } from '../types';
import type { ExtractionSchemaProperty } from '../types';

// ─── Template Definitions ─────────────────────────────────────────────────────

export interface AgentTemplate {
    id: string;
    emoji: string;
    title: string;
    subtitle: string;
    color: string;          // Tailwind gradient classes
    borderColor: string;
    config: Partial<AgentConfig> & { extraction_schema?: ExtractionSchemaProperty[] };
}

export const AGENT_TEMPLATES: AgentTemplate[] = [
    {
        id: 'inmobiliaria',
        emoji: '🏠',
        title: 'Inmobiliaria',
        subtitle: 'Cualifica leads y agenda visitas a inmuebles',
        color: 'from-blue-500 to-indigo-600',
        borderColor: 'border-blue-200',
        config: {
            name: 'Agente Inmobiliaria',
            use_case: 'Cualificación de leads y agendamiento de visitas',
            description: 'Agente especializado en el sector inmobiliario. Cualifica el interés del cliente, recoge su presupuesto y disponibilidad para coordinar visitas.',
            greeting: 'Buenas, le llamo de parte de la agencia inmobiliaria. ¿Tiene un momento para comentarle algunas propiedades que podrían interesarle?',
            instructions: `Tu objetivo es cualificar a clientes potenciales interesados en comprar o alquilar inmuebles.

GUION:
1. Preséntate brevemente y confirma que hablas con la persona correcta.
2. Pregunta si busca compra o alquiler.
3. Pregunta por la zona o barrio preferido.
4. Pregunta cuál es su presupuesto máximo aproximado.
5. Pregunta cuántas habitaciones necesita.
6. Pregunta si estaría disponible para una visita esta semana o la próxima.
7. Pregunta en qué plazo está pensando hacer la operación.
8. Si está interesado y disponible, comenta que un asesor le contactará para concretar la visita.
9. Cierra agradeciendo su tiempo.`,
            critical_rules: 'No des información sobre inmuebles concretos. Tu misión es recoger datos para que el equipo comercial haga el seguimiento. Si el cliente pregunta por precios específicos, di que el asesor se los facilitará en la visita.',
            tipo_resultados: 'CUALIFICACION_LEAD',
            extraction_schema: [
                { key: 'tipo_operacion', type: 'enum', label: 'Compra o alquiler', options: ['compra', 'alquiler', 'ambos'] },
                { key: 'zona_preferida', type: 'text', label: 'Zona preferida' },
                { key: 'presupuesto_max', type: 'number', label: 'Presupuesto máximo (€)' },
                { key: 'habitaciones', type: 'enum', label: 'Habitaciones', options: ['1', '2', '3', '4+'] },
                { key: 'disponible_visita', type: 'boolean', label: 'Disponible para visita' },
                { key: 'plazo_operacion', type: 'enum', label: 'Plazo de compra/alquiler', options: ['inmediato', '1-3 meses', '3-6 meses', 'más de 6 meses'] },
            ],
        },
    },
    {
        id: 'cita_medica',
        emoji: '🏥',
        title: 'Cita Médica',
        subtitle: 'Confirma, cancela o reagenda citas con pacientes',
        color: 'from-green-500 to-emerald-600',
        borderColor: 'border-green-200',
        config: {
            name: 'Agente Citas Médicas',
            use_case: 'Confirmación y reagendamiento de citas',
            description: 'Agente sanitario que confirma citas médicas pendientes, gestiona cancelaciones y ofrece nuevos horarios disponibles.',
            greeting: 'Buenos días, le llamo del centro médico para confirmar su cita. ¿Es usted la persona que tiene cita programada con nosotros?',
            instructions: `Tu objetivo es confirmar citas médicas y gestionar cambios o cancelaciones.

GUION:
1. Confírma que hablas con el/la paciente correcto/a.
2. Informa de la fecha y hora de la cita que tienen registrada.
3. Pregunta si puede confirmar su asistencia.
4. Si confirma: agradece y recuerda traer tarjeta sanitaria y DNI.
5. Si no puede asistir: ofrece reagendar (indica que un gestor le llamará para buscar nueva fecha) o cancelar.
6. Si cancela: confirma la cancelación y cierra amablemente.
7. Pregunta si tiene alguna duda o necesidad especial para la visita.`,
            critical_rules: 'No muestres datos médicos del paciente. No confirmes diagnósticos ni resultados. Si el paciente pregunta por resultados médicos, deriva al médico responsable.',
            tipo_resultados: 'AGENDAMIENTO_CITA',
            extraction_schema: [
                { key: 'confirma_cita', type: 'boolean', label: 'Confirma asistencia' },
                { key: 'motivo_cancelacion', type: 'enum', label: 'Motivo de cancelación', options: ['trabajo', 'se encuentra bien', 'otro médico', 'olvido', 'otro'] },
                { key: 'quiere_reagendar', type: 'boolean', label: 'Quiere reagendar' },
                { key: 'necesidades_especiales', type: 'text', label: 'Necesidades especiales para la visita' },
            ],
        },
    },
    {
        id: 'encuesta_satisfaccion',
        emoji: '⭐',
        title: 'Encuesta de Satisfacción',
        subtitle: 'Recoge valoraciones post-servicio de tus clientes',
        color: 'from-yellow-500 to-orange-500',
        borderColor: 'border-yellow-200',
        config: {
            name: 'Encuesta Satisfacción',
            use_case: 'Medición de satisfacción post-servicio',
            description: 'Encuesta de satisfacción del cliente tras recibir el servicio. Recoge valoraciones numéricas, detecta promotores y recoge comentarios cualitativos.',
            greeting: 'Buenas, le llamo para conocer su opinión sobre el servicio que recibió recientemente. Solo le llevará un minuto, ¿tiene un momento?',
            instructions: `Tu objetivo es recoger la valoración del cliente sobre el servicio recibido.

GUION:
1. Explica brevemente el motivo de la llamada (encuesta de satisfacción).
2. Pregunta: "Del 1 al 10, ¿cómo valoraría la atención recibida?"
3. Pregunta: "Y el resultado o resolución de su solicitud, ¿del 1 al 10?"
4. Pregunta: "¿Recomendaría nuestros servicios a un familiar o amigo?" (Sí/No)
5. Si la nota es baja (menor a 7): pregunta cuál fue el principal motivo de la baja valoración.
6. Si la nota es alta (7 o más): pregunta qué es lo que más valoró del servicio.
7. Cierra agradeciendo su tiempo y su confianza.`,
            critical_rules: 'Si el cliente se muestra molesto o pone una nota muy baja, valida su malestar con empatía antes de continuar. No tomes decisiones ni ofrezcas compensaciones — registra el motivo y cierra amablemente.',
            tipo_resultados: 'ENCUESTA_MIXTA',
            extraction_schema: [
                { key: 'nota_atencion', type: 'number', label: 'Nota atención (1-10)' },
                { key: 'nota_resolucion', type: 'number', label: 'Nota resolución (1-10)' },
                { key: 'recomendaria', type: 'boolean', label: 'Recomendaría el servicio' },
                { key: 'motivo_baja_nota', type: 'text', label: 'Motivo de baja valoración' },
                { key: 'punto_positivo', type: 'text', label: 'Lo que más valoró' },
            ],
        },
    },
    {
        id: 'ventas_b2b',
        emoji: '💼',
        title: 'Ventas B2B',
        subtitle: 'Prospección y cualificación de leads empresariales',
        color: 'from-purple-500 to-violet-600',
        borderColor: 'border-purple-200',
        config: {
            name: 'Agente Ventas B2B',
            use_case: 'Prospección y cualificación de leads empresariales',
            description: 'Agente de ventas para prospección B2B. Identifica el cargo del interlocutor, detecta necesidades y cualifica si es un lead con potencial de compra.',
            greeting: 'Buenas, le llamo porque creo que nuestra solución puede ser muy relevante para su empresa. ¿Tiene dos minutos para que le explique brevemente de qué se trata?',
            instructions: `Tu objetivo es cualificar leads empresariales y detectar oportunidades de venta.

GUION:
1. Confirma que hablas con la persona adecuada (decisor o influenciador).
2. Pregunta cuál es su cargo en la empresa.
3. Pregunta por el número aproximado de empleados de la empresa.
4. Pregunta si actualmente usan alguna herramienta o proveedor similar.
5. Pregunta cuál es su mayor reto o punto de dolor en el área en cuestión.
6. Valora si hay presupuesto o interés en explorar alternativas.
7. Si hay interés: propón una reunión o demostración con el equipo comercial.
8. Si no hay interés: agradece el tiempo y cierra dejando la puerta abierta.`,
            critical_rules: 'No hagas promesas de precio o características específicas del producto. Tu misión es detectar interés y recoger información para el equipo de ventas. Si preguntan por precios, di que depende del caso y que el equipo comercial les preparará una propuesta.',
            tipo_resultados: 'CUALIFICACION_LEAD',
            extraction_schema: [
                { key: 'cargo_interlocutor', type: 'text', label: 'Cargo del interlocutor' },
                { key: 'tamano_empresa', type: 'enum', label: 'Tamaño empresa', options: ['1-10', '11-50', '51-200', '200+'] },
                { key: 'usa_solucion_similar', type: 'boolean', label: 'Usa solución similar actualmente' },
                { key: 'proveedor_actual', type: 'text', label: 'Proveedor actual' },
                { key: 'punto_dolor', type: 'text', label: 'Principal reto o punto de dolor' },
                { key: 'nivel_interes', type: 'enum', label: 'Nivel de interés', options: ['alto', 'medio', 'bajo', 'ninguno'] },
                { key: 'acepta_reunion', type: 'boolean', label: 'Acepta reunión o demo' },
            ],
        },
    },
    {
        id: 'nps',
        emoji: '📊',
        title: 'NPS Rápido',
        subtitle: 'Net Promoter Score en menos de 2 minutos',
        color: 'from-teal-500 to-cyan-600',
        borderColor: 'border-teal-200',
        config: {
            name: 'Encuesta NPS',
            use_case: 'Net Promoter Score y feedback cualitativo',
            description: 'Encuesta NPS ultrabreve. Recoge la puntuación de recomendación (0-10) y un motivo corto. Máximo 2 minutos de duración.',
            greeting: 'Hola, le llamo para hacerle una única pregunta sobre su experiencia con nosotros. Solo tardará un momento, ¿me permite?',
            instructions: `Tu objetivo es obtener el NPS y un breve motivo del cliente.

GUION:
1. Haz la pregunta NPS: "Del 0 al 10, ¿con qué probabilidad recomendaría nuestra empresa a un amigo o familiar?"
2. Si da una nota entre 0 y 6 (detractor): pregunta "¿Qué tendríamos que mejorar para que esa nota fuera más alta?"
3. Si da una nota entre 7 y 8 (pasivo): pregunta "¿Qué es lo que más le ha gustado y qué mejoraría?"
4. Si da una nota entre 9 y 10 (promotor): pregunta "¡Muchas gracias! ¿Qué es lo que más valora de nosotros?"
5. Cierra agradeciendo su opinión y diciéndole que su feedback es muy valioso.`,
            critical_rules: 'La encuesta debe ser muy breve. Máximo 3 turnos de conversación. No te alargues en explicaciones. Si el cliente quiere hablar más, escúchale pero cierra en cuanto tengas la nota y el motivo.',
            tipo_resultados: 'ENCUESTA_NUMERICA',
            extraction_schema: [
                { key: 'nps_score', type: 'number', label: 'Puntuación NPS (0-10)' },
                { key: 'categoria_nps', type: 'enum', label: 'Categoría NPS', options: ['promotor', 'pasivo', 'detractor'] },
                { key: 'motivo_puntuacion', type: 'text', label: 'Motivo de la puntuación' },
            ],
        },
    },
    {
        id: 'soporte_incidencia',
        emoji: '🔧',
        title: 'Soporte / Incidencias',
        subtitle: 'Recoge datos de incidencias para abrir tickets',
        color: 'from-red-500 to-rose-600',
        borderColor: 'border-red-200',
        config: {
            name: 'Agente Soporte',
            use_case: 'Recogida de datos de incidencias y soporte técnico',
            description: 'Agente de soporte para recoger información de una incidencia o problema reportado por el cliente. Categoriza el problema y recoge datos para el ticket.',
            greeting: 'Buenas, le llamo del servicio de soporte técnico en relación a la incidencia que notificó. ¿Tiene un momento para que lo revisemos?',
            instructions: `Tu objetivo es recoger toda la información necesaria para gestionar la incidencia del cliente.

GUION:
1. Confirma los datos del cliente y que siguen teniendo el problema.
2. Pregunta una descripción breve del problema.
3. Pregunta desde cuándo ocurre el problema.
4. Pregunta si el problema es continuo o intermitente.
5. Pregunta si han intentado alguna solución por su cuenta.
6. Evalúa la urgencia: ¿está afectando al negocio o a procesos críticos?
7. Informa de que con estos datos el equipo técnico abrirá un ticket y se pondrá en contacto.
8. Da un número de referencia genérico (ej: "quedará registrado y recibirá un correo de confirmación").`,
            critical_rules: 'No ofrezcas soluciones técnicas concretas. Tu misión es recoger datos. No hagas promesas de tiempos de resolución. Si el cliente está muy enfadado, valida su frustración antes de continuar.',
            tipo_resultados: 'SOPORTE_CLIENTE',
            extraction_schema: [
                { key: 'descripcion_problema', type: 'text', label: 'Descripción del problema' },
                { key: 'tiempo_desde_incidencia', type: 'enum', label: 'Tiempo desde incidencia', options: ['hoy', 'esta semana', 'más de una semana', 'más de un mes'] },
                { key: 'frecuencia', type: 'enum', label: 'Frecuencia del problema', options: ['continuo', 'intermitente', 'ocurrió una vez'] },
                { key: 'intento_solucion', type: 'boolean', label: 'Intentó solución propia' },
                { key: 'urgencia_alta', type: 'boolean', label: 'Afecta a negocio crítico' },
            ],
        },
    },
];

// ─── Component ────────────────────────────────────────────────────────────────

interface Props {
    onSelectTemplate: (config: AgentTemplate['config']) => void;
    onClose: () => void;
}

export const AgentTemplateGallery: React.FC<Props> = ({ onSelectTemplate, onClose }) => {
    const { t } = useTranslation();
    const [hoveredId, setHoveredId] = useState<string | null>(null);

    return (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-[100] p-4">
            <div className="bg-white rounded-2xl shadow-2xl w-full max-w-3xl max-h-[90vh] flex flex-col overflow-hidden animate-in fade-in zoom-in duration-200">

                {/* Header */}
                <div className="px-7 py-5 border-b border-gray-100 flex justify-between items-center shrink-0">
                    <div>
                        <h2 className="text-xl font-bold text-gray-900 flex items-center gap-2">
                            <Sparkles size={20} className="text-blue-500" />
                            {t('Elige una plantilla', 'Elige una plantilla')}
                        </h2>
                        <p className="text-sm text-gray-500 mt-0.5">
                            {t('Precarga el guion, instrucciones y esquema de datos. Podrás editarlos después.', 'Precarga el guion, instrucciones y esquema de datos. Podrás editarlos después.')}
                        </p>
                    </div>
                    <button
                        onClick={onClose}
                        className="w-8 h-8 flex items-center justify-center text-gray-400 hover:text-gray-900 bg-gray-100 hover:bg-gray-200 rounded-full transition-all"
                    >
                        <X size={16} />
                    </button>
                </div>

                {/* Template grid */}
                <div className="p-6 overflow-y-auto grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                    {AGENT_TEMPLATES.map(template => (
                        <button
                            key={template.id}
                            onClick={() => onSelectTemplate(template.config)}
                            onMouseEnter={() => setHoveredId(template.id)}
                            onMouseLeave={() => setHoveredId(null)}
                            className={`group relative text-left p-5 rounded-2xl border-2 transition-all duration-200 hover:shadow-lg hover:scale-[1.02] active:scale-[0.99] ${hoveredId === template.id ? template.borderColor : 'border-gray-100'}`}
                        >
                            {/* Gradient badge */}
                            <div className={`w-12 h-12 rounded-2xl bg-gradient-to-br ${template.color} flex items-center justify-center text-2xl mb-3 shadow-sm`}>
                                {template.emoji}
                            </div>

                            <h3 className="font-bold text-gray-900 text-sm mb-1">{template.title}</h3>
                            <p className="text-xs text-gray-500 leading-relaxed">{template.subtitle}</p>

                            {/* Schema pill count */}
                            {template.config.extraction_schema && (
                                <div className="mt-3 flex items-center gap-1.5">
                                    <span className="text-[10px] bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full font-medium">
                                        {template.config.extraction_schema.length} campos dinámicos
                                    </span>
                                </div>
                            )}

                            <ChevronRight
                                size={16}
                                className={`absolute right-4 top-1/2 -translate-y-1/2 text-gray-300 transition-all ${hoveredId === template.id ? 'text-gray-600 translate-x-1' : ''}`}
                            />
                        </button>
                    ))}

                    {/* Blank option */}
                    <button
                        onClick={() => onSelectTemplate({})}
                        onMouseEnter={() => setHoveredId('blank')}
                        onMouseLeave={() => setHoveredId(null)}
                        className={`group relative text-left p-5 rounded-2xl border-2 border-dashed transition-all duration-200 hover:shadow-md hover:scale-[1.02] active:scale-[0.99] ${hoveredId === 'blank' ? 'border-gray-400 bg-gray-50' : 'border-gray-200'}`}
                    >
                        <div className="w-12 h-12 rounded-2xl bg-gray-100 flex items-center justify-center text-2xl mb-3">
                            ✏️
                        </div>
                        <h3 className="font-bold text-gray-700 text-sm mb-1">{t('Desde cero', 'Desde cero')}</h3>
                        <p className="text-xs text-gray-400 leading-relaxed">{t('Crea un agente completamente personalizado', 'Crea un agente completamente personalizado')}</p>
                        <ChevronRight
                            size={16}
                            className={`absolute right-4 top-1/2 -translate-y-1/2 text-gray-300 transition-all ${hoveredId === 'blank' ? 'text-gray-500 translate-x-1' : ''}`}
                        />
                    </button>
                </div>
            </div>
        </div>
    );
};
