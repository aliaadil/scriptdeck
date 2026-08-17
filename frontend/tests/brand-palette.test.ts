import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { describe, it, expect } from 'vitest';

// NB: read from disk rather than `import('../src/index.css?raw')`. Vitest runs with
// `css: false` by default, which stubs CSS imports to an empty string regardless of
// the `?raw` query, so an import-based assertion can never observe the real file.
//
// The path is anchored to this test file rather than process.cwd() so it holds no
// matter which directory the runner is invoked from. `testPath` is only populated
// while a test is executing, hence the lazy read.
function readIndexCss(): string {
  const testPath = expect.getState().testPath;
  if (!testPath) throw new Error('testPath unavailable; read must happen inside a test');
  return readFileSync(resolve(dirname(testPath), '../src/index.css'), 'utf8');
}

describe('brand palette CSS variables', () => {
  it('reads the real stylesheet', () => {
    // Identity guard: proves the assertions below run against the actual
    // stylesheet rather than an empty or unrelated file.
    expect(readIndexCss()).toMatch(/@tailwind base/);
  });

  it('exposes the Kindling palette tokens', () => {
    const css = readIndexCss();
    expect(css).toMatch(/--kindling-ember:\s*#dc2626/);
    expect(css).toMatch(/--kindling-spark:\s*#fb923c/);
    expect(css).toMatch(/--kindling-flame:\s*#facc15/);
    expect(css).toMatch(/--kindling-charcoal:\s*#0c0a09/);
    expect(css).toMatch(/--kindling-text:\s*#f5f5f4/);
  });
});
