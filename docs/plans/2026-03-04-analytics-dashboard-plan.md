# Panel Premium Analítico Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implementar un dashboard analítico premium y componentes visuales específicos por tipo de campaña en la vista tabular superior y dentro de las filas de resultados.

**Architecture:** Modificaremos `ResultsView.tsx` para inyectar `<AnalyticsDashboard />` sobre la tabla estilizadamente cuando se filtre por una campaña o agente específico que permita deducir el `agent_type`. Refactorizaremos la celda "Results / Scores" de la tabla para soportar badges visuales avanzados usando la columna `datos_extra`.

**Tech Stack:** React, TailwindCSS, Lucide React, Supabase, Groq/LLMs.

---

### Task 1: Deducir `agent_type` activo e Inyectar el Dashboard

**Files:**
- Modify: `views/ResultsView.tsx`

**Step 1: Identificar el tipo de agente actual**
Modificar la lógica en `ResultsView.tsx` para que si se selecciona un `campaignId` o `agentId` específico, extraiga el `tipo_resultados` predominante de los `filteredResults`.

```typescript
const activeAgentType = useMemo(() => {
    if (selectedTipo !== 'all') return selectedTipo;
    if (filteredResults.length > 0 && (selectedAgentId !== 'all' || campaignId)) {
        return filteredResults[0].tipo_resultados || 'PREGUNTAS_ABIERTAS';
    }
    return null;
}, [filteredResults, selectedTipo, selectedAgentId, campaignId]);
```

**Step 2: Inyectar AnalyticsDashboard**
Renderizar el componente `AnalyticsDashboard` justo debajo de los filtros y encima de la tabla, envuelto en una sutil animación si `activeAgentType` existe y hay resultados.

```tsx
{/* Dashboard Section */}
{activeAgentType && filteredResults.length > 0 && (
    <div className="mb-6">
        <AnalyticsDashboard 
            tipoResultados={activeAgentType} 
            results={filteredResults} 
        />
    </div>
)}
```

**Step 3: Commit**
```bash
git add views/ResultsView.tsx
git commit -m "feat: render analytics dashboard conditionally based on active agent type"
```

---

### Task 2: Actualizar la Celda de Resultados en la Tabla (`ResultsView.tsx`)

**Files:**
- Modify: `views/ResultsView.tsx`

**Step 1: Parsear `datos_extra` para Leads y Citas**
Dentro del `map` de `filteredResults`, en la columna "Results / Scores", añadir casos para `CUALIFICACION_LEAD` y `AGENDAMIENTO_CITA` que lean `row.datos_extra`.

```tsx
if (type === 'CUALIFICACION_LEAD') {
    const isLead = row.datos_extra?.lead_cualificado;
    return (
        <div className="flex flex-col items-center">
            <Badge />
            {isLead === true ? (
                <span className="flex items-center gap-1 bg-green-100 text-green-700 text-xs px-2 py-1 rounded-md font-bold shadow-sm">
                    <Target size={14} /> HOT LEAD
                </span>
            ) : isLead === false ? (
                <span className="flex items-center gap-1 bg-red-100 text-red-700 text-xs px-2 py-1 rounded-md font-bold shadow-sm">
                    <ThumbsDown size={14} /> DESCARTADO
                </span>
            ) : (
                <span className="text-gray-400 text-xs">-</span>
            )}
        </div>
    );
} else if (type === 'AGENDAMIENTO_CITA') {
    const hasCita = row.datos_extra?.cita_agendada;
    const fecha = row.datos_extra?.fecha_cita;
    return (
        <div className="flex flex-col items-center">
            <Badge />
            {hasCita ? (
                <div className="bg-purple-100 text-purple-800 text-xs px-3 py-1.5 rounded-lg border border-purple-200 text-center font-medium shadow-sm">
                    <Clock size={14} className="inline mr-1" />
                    {fecha || 'Cita Agendada'}
                </div>
            ) : (
                <span className="text-gray-400 text-xs">Sin fecha</span>
            )}
        </div>
    );
}
```

**Step 2: Asegurar la importación de iconos**
Importar los iconos necesarios (`Target`, `ThumbsDown`, `Clock`) de `lucide-react` en `ResultsView.tsx`.

**Step 3: Commit**
```bash
git add views/ResultsView.tsx
git commit -m "feat: enhance table cells with visual badges for leads and meetings using datos_extra"
```
