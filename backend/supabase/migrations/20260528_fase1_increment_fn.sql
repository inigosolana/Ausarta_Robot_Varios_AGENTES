-- Función RPC para incremento atómico de llamadas_consumidas_mes.
-- Usada por el backend (Fase 1 SaaS) para evitar race conditions en
-- entornos con múltiples workers paralelos.
CREATE OR REPLACE FUNCTION public.increment_llamadas_consumidas(p_empresa_id INTEGER)
RETURNS void
LANGUAGE sql
SECURITY DEFINER
AS $$
  UPDATE public.empresas
  SET llamadas_consumidas_mes = COALESCE(llamadas_consumidas_mes, 0) + 1
  WHERE id = p_empresa_id;
$$;
