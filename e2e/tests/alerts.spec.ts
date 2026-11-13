import { test, expect, type APIRequestContext } from '@playwright/test';
import { INGEST_KEY, OPERATOR, VIEWER, uniqueTimestamp } from './helpers';

async function newFireAlert(request: APIRequestContext, nodeId: string) {
  const response = await request.post('readings/', {
    headers: { 'X-API-Key': INGEST_KEY },
    data: {
      node_id: nodeId,
      temperature: 95,
      humidity: 8,
      smoke: 95,
      flame: true,
      timestamp: uniqueTimestamp(),
    },
  });
  expect(response.status()).toBe(201);
  const { alert_id } = await response.json();
  expect(alert_id).not.toBeNull();
  return alert_id as number;
}

test.describe('gestión de alertas', () => {
  test('un usuario sin permiso no puede reconocer ni cerrar una alerta', async ({ request }) => {
    const id = await newFireAlert(request, 'SIM-006');

    const acknowledge = await request.post(`alerts/${id}/acknowledge/`, { headers: { Authorization: VIEWER } });
    const close = await request.post(`alerts/${id}/close/`, { headers: { Authorization: VIEWER } });

    expect(acknowledge.status()).toBe(403);
    expect(close.status()).toBe(403);
  });

  test('sin token no se puede reconocer una alerta', async ({ request }) => {
    const response = await request.post('alerts/1/acknowledge/');

    expect([401, 403]).toContain(response.status());
  });

  test('el operador reconoce y luego cierra una alerta', async ({ request }) => {
    const id = await newFireAlert(request, 'SIM-002');
    const auth = { Authorization: OPERATOR };

    const acknowledged = await request.post(`alerts/${id}/acknowledge/`, { headers: auth });
    expect(acknowledged.status()).toBe(200);
    expect((await acknowledged.json()).status).toBe('ACKNOWLEDGED');

    const closed = await request.post(`alerts/${id}/close/`, { headers: auth });
    expect(closed.status()).toBe(200);
    expect((await closed.json()).status).toBe('CLOSED');
  });

  test('una alerta cerrada no se puede reconocer otra vez', async ({ request }) => {
    const id = await newFireAlert(request, 'SIM-004');
    const auth = { Authorization: OPERATOR };
    await request.post(`alerts/${id}/close/`, { headers: auth });

    const again = await request.post(`alerts/${id}/acknowledge/`, { headers: auth });

    expect(again.status()).toBeGreaterThanOrEqual(400);
    expect(again.status()).toBeLessThan(500);
  });

  test('una alerta que no existe responde 404', async ({ request }) => {
    const response = await request.get('alerts/99999999/');

    expect(response.status()).toBe(404);
  });
});
