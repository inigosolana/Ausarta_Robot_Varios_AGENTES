/**
 * Fetchers de métricas admin (LiveKit + Redis) con autenticación Bearer.
 */
import { apiFetch } from './apiFetch';
import type { LiveCallsMetricsResponse, RedisMetricsResponse } from '../types';

export async function fetchLiveCallsMetrics(): Promise<LiveCallsMetricsResponse> {
  const res = await apiFetch('/api/admin/metrics/live-calls');
  if (!res.ok) {
    throw new Error(`Error métricas LiveKit (${res.status})`);
  }
  return res.json();
}

export async function fetchRedisMetrics(): Promise<RedisMetricsResponse> {
  const res = await apiFetch('/api/admin/metrics/redis');
  if (!res.ok) {
    throw new Error(`Error métricas Redis (${res.status})`);
  }
  return res.json();
}
