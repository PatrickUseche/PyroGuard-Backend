import { test, expect } from '@playwright/test';
import { INGEST_KEY, uniqueTimestamp, reading } from './helpers';

const headers = { 'X-API-Key': INGEST_KEY };

test.describe('ingesta de lecturas', () => {
  test('rechaza la lectura sin clave de ingesta o con una clave incorrecta', async ({ request }) => {
    const without = await request.post('readings/', { data: reading() });
    const wrong = await request.post('readings/', { headers: { 'X-API-Key': 'incorrecta' }, data: reading() });

    expect([401, 403]).toContain(without.status());
    expect([401, 403]).toContain(wrong.status());
  });

  test('guarda una lectura normal y devuelve su nivel de riesgo', async ({ request }) => {
    const response = await request.post('readings/', {
      headers,
      data: reading({ timestamp: uniqueTimestamp() }),
    });

    expect(response.status()).toBe(201);
    const body = await response.json();
    expect(body.risk_level).toBe('NORMAL');
    expect(body.alert_id ?? null).toBeNull();
  });

  test('una lectura de incendio crea una alerta', async ({ request }) => {
    const response = await request.post('readings/', {
      headers,
      data: reading({
        node_id: 'SIM-005',
        temperature: 95,
        humidity: 8,
        smoke: 95,
        flame: true,
        timestamp: uniqueTimestamp(),
      }),
    });

    expect(response.status()).toBe(201);
    const body = await response.json();
    expect(body.risk_level).toBe('FIRE');
    expect(body.alert_id).not.toBeNull();
  });

  test('la misma lectura enviada dos veces se guarda una sola vez', async ({ request }) => {
    const data = reading({ timestamp: uniqueTimestamp() });

    const first = await request.post('readings/', { headers, data });
    const second = await request.post('readings/', { headers, data });

    expect(first.status()).toBe(201);
    expect(second.status()).toBe(200);
    expect((await second.json()).status).toBe('duplicate');
  });

  test('un reintento simultáneo del mismo envío no deja lecturas repetidas', async ({ request }) => {
    const data = reading({ timestamp: uniqueTimestamp() });

    const responses = await Promise.all(
      Array.from({ length: 8 }, () => request.post('readings/', { headers, data })),
    );

    const codes = responses.map((response) => response.status());
    expect(codes.filter((code) => code === 201)).toHaveLength(1);
    expect(codes.filter((code) => code === 200)).toHaveLength(7);
    expect(codes.filter((code) => code >= 500)).toHaveLength(0);
  });

  test('valida los rangos y devuelve los errores en español', async ({ request }) => {
    const response = await request.post('readings/', {
      headers,
      data: reading({ humidity: 150, temperature: 999, timestamp: uniqueTimestamp() }),
    });

    expect(response.status()).toBe(400);
    const text = JSON.stringify(await response.json());
    expect(text).toMatch(/humedad/i);
    expect(text).toMatch(/temperatura/i);
  });

  test('rechaza un nodo que no existe y una fecha en el futuro', async ({ request }) => {
    const unknown = await request.post('readings/', {
      headers,
      data: reading({ node_id: 'NO-EXISTE', timestamp: uniqueTimestamp() }),
    });
    const future = await request.post('readings/', {
      headers,
      data: reading({ timestamp: new Date(Date.now() + 3_600_000).toISOString() }),
    });

    expect(unknown.status()).toBe(400);
    expect(future.status()).toBe(400);
    expect(JSON.stringify(await future.json())).toMatch(/futuro/i);
  });

  test('rechaza una lectura con campos obligatorios ausentes', async ({ request }) => {
    const response = await request.post('readings/', { headers, data: { node_id: 'SIM-004' } });

    expect(response.status()).toBe(400);
  });
});
