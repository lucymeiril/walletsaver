import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { cwd } from 'node:process';

describe('DataReview AI provider loading regression', () => {
  it('does not fetch ai-admin providers directly from the browser', () => {
    const source = readFileSync(join(cwd(), 'src', 'pages', 'DataReview', 'DataReviewPage.jsx'), 'utf8');

    expect(source).toContain('api.getAiProviders');
    expect(source).not.toMatch(/fetch\s*\(\s*`?\$\{[^}]+}\s*\/api\/providers/);
    expect(source).not.toContain('http://localhost:8003' + '/api/providers');
  });
});
