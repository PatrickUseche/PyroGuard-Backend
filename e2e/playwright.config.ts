import { defineConfig } from '@playwright/test';

// Pruebas de la API real contra un backend LOCAL (nunca contra producción).
// Requiere el servidor en http://localhost:8000 con datos de `seed_demo` y los tokens de
// prueba en E2E_OPERATOR_TOKEN y E2E_VIEWER_TOKEN (ver README.md de esta carpeta).
export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: !!process.env['CI'],
  retries: process.env['CI'] ? 1 : 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: process.env['E2E_API_URL'] ?? 'http://localhost:8000/api/',
    extraHTTPHeaders: { Accept: 'application/json' },
    trace: 'retain-on-failure',
  },
});
