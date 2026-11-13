import { randomUUID } from 'node:crypto';

export const INGEST_KEY = process.env['E2E_INGEST_API_KEY'] ?? 'e2e-ingest-key';
export const OPERATOR = `Token ${process.env['E2E_OPERATOR_TOKEN'] ?? ''}`;
export const VIEWER = `Token ${process.env['E2E_VIEWER_TOKEN'] ?? ''}`;

/** Lectura válida con valores normales; cada llamada usa un timestamp distinto. */
export function reading(overrides: Record<string, unknown> = {}, secondsAgo = 0) {
  return {
    node_id: 'SIM-004',
    temperature: 24,
    humidity: 55,
    smoke: 12,
    flame: false,
    timestamp: new Date(Date.now() - secondsAgo * 1000 - Math.floor(Math.random() * 1000)).toISOString(),
    ...overrides,
  };
}

/** Marca de tiempo única (microsegundos aleatorios) para no chocar con otras ejecuciones. */
export function uniqueTimestamp() {
  const base = new Date(Date.now() - 60_000);
  return `${base.toISOString().slice(0, 19)}.${randomUUID().replace(/\D/g, '').slice(0, 6).padEnd(6, '0')}Z`;
}
