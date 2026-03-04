# Diseño Funcional: Panel Premium Analítico (ResultsView)

## Resumen Ejecutivo
Implementación de un panel analítico estilo "Dashboard Premium" en la vista de resultados de campañas (`ResultsView.tsx`) en la aplicación frontend de Ausarta. Este panel proporcionará visualizaciones adaptadas dinámicamente al tipo de agente (`agent_type`) que ha ejecutado la campaña, proporcionando una vista de alto nivel superior a la tabla detallada.

## 1. Experiencia de Usuario y Comportamiento Visivo
- **Expansión Dinámica**: El panel será invisible si el usuario está viendo "Todos los resultados". Solamente se expandirá (con una sutil animación `framer-motion` o tailwind-animate) cuando el usuario seleccione una campaña específica.
- **Jerarquía Visual**: El Dashboard se posicionará en la parte superior, justo debajo de los filtros y encima de la tabla de registros numéricos.
- **Aesthetic**: Uso de estilos premium. Sombras sutiles (`shadow-sm`, `shadow-md`), bordes finos, esquinas redondeadas (`rounded-2xl`), y en ocasiones, elementos tipo "glassmorphism" o gradientes para enfatizar datos positivos.

## 2. Tipos de Visualización por Tipo de Agente
Dependiendo de qué tipo sea el agente asignado a la campaña en cuestión (`agent_type` o fallback deducido).

**A. ENCUESTA_NUMERICA**
- Tarjetas superiores mostrando la nota media global calculada en base a las variables `puntuacion_comercial`, `puntuacion_instalador` y `puntuacion_rapidez`.
- Gráfico de barras evolutivo por fecha, usando `recharts`, comparando las tres notas medias a lo largo del periodo seleccionado.

**B. CUALIFICACION_LEAD**
- Gráfico circular tipo Donut o Pie Chart con los Leads Calientes (Cualificados) vs Basura (No Cualificados).
- Análisis visual del ratio de conversión y el "Impacto Comercial" (leads listos para contactar).

**C. PREGUNTAS_ABIERTAS / SOPORTE_CLIENTE / AGENDAMIENTO_CITA**
- Listado tipo "Dashboard Feed" ("Estilo Twitter") con los 3-4 comentarios o insigths más destacados de la campaña. Renderizado en tarjetas separadas del grid habitual.

## 3. Arquitectura Frontend (React Component)
El módulo principal será `AnalyticsDashboard.tsx`.
- Recibirá como props `results` (los datos extraídos y filtrados de la tabla) y `tipoResultados` (el tipo al que pertenece la campaña).
- Se modificará `ResultsView.tsx` para inyectarlo dependiendo de si hay un selector de campañas aplicado activo.

## 4. Dependencias Claves
- `recharts` para las gráficas.
- `lucide-react` para iconografía complementaria.
- Datos extraídos del backend (JSON almacenados en Supabase bajo la columna `datos_extra` e insertados con anterioridad gracias a procesamiento LLM).
