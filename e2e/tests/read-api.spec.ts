import { test, expect } from '@playwright/test';
import { OPERATOR, VIEWER } from './helpers';

test.describe('consultas y autenticación', () => {
  test('health responde 200 en JSON', async ({ request }) => {
    const response = await request.get('health/');

    expect(response.status()).toBe(200);
    expect(response.headers()['content-type']).toContain('application/json');
  });

  test('el resumen del panel tiene coherencia interna', async ({ request }) => {
    const summary = await (await request.get('dashboard/summary/')).json();

    expect(summary.total_nodes).toBe(
      summary.nodes_online + summary.nodes_offline + summary.nodes_unknown,
    );
    expect(['NORMAL', 'WARNING', 'FIRE']).toContain(summary.overall_risk);
    expect(summary.nodes_at_risk).toBeLessThanOrEqual(summary.nodes_online);
  });

  test('un nodo inexistente responde 404 con mensaje en español', async ({ request }) => {
    const response = await request.get('nodes/NO-EXISTE/status/');

    expect(response.status()).toBe(404);
    const body = await response.json();
    expect(body.status).toBe('error');
    expect(JSON.stringify(body)).not.toMatch(/matches the given query/i);
  });

  test('una ruta desconocida de la API responde JSON y no HTML', async ({ request }) => {
    const response = await request.get('no-existe/');

    expect(response.status()).toBe(404);
    expect(response.headers()['content-type']).toContain('application/json');
  });

  test('/auth/me/ exige un token válido', async ({ request }) => {
    const anonymous = await request.get('auth/me/');
    const invalid = await request.get('auth/me/', { headers: { Authorization: 'Token invalido' } });
    const valid = await request.get('auth/me/', { headers: { Authorization: OPERATOR } });

    expect(anonymous.status()).toBe(401);
    expect(invalid.status()).toBe(401);
    expect(valid.status()).toBe(200);
    expect((await valid.json()).can_manage_alerts).toBe(true);
  });

  test('un usuario sin grupo no puede gestionar alertas', async ({ request }) => {
    const me = await (await request.get('auth/me/', { headers: { Authorization: VIEWER } })).json();

    expect(me.can_manage_alerts).toBe(false);
  });
});
