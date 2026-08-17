import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, it, expect } from 'vitest';

// NB: read from disk rather than `import('../src/index.css?raw')`. Vitest runs with
// `css: false` by default, which stubs CSS imports to an empty string regardless of
// the `?raw` query, so an import-based assertion can never observe the real file.
const cssPath = resolve(process.cwd(), 'src/index.css');

describe('brand palette CSS variables', () => {
  const css = readFileSync(cssPath, 'utf8');

  it('reads the real stylesheet', () => {
    expect(css.length).toBeGreaterThan(0);
  });

  it('exposes the Kindling palette tokens', () => {
    expect(css).toMatch(/--kindling-ember:\s*#dc2626/);
    expect(css).toMatch(/--kindling-spark:\s*#fb923c/);
    expect(css).toMatch(/--kindling-flame:\s*#facc15/);
    expect(css).toMatch(/--kindling-charcoal:\s*#0c0a09/);
    expect(css).toMatch(/--kindling-text:\s*#f5f5f4/);
  });
});
