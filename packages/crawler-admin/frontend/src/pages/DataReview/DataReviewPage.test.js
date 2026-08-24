import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { cwd } from 'node:process';

describe('DataReview legacy ai-admin removal', () => {
  it('does not expose live ai-admin address/provider/send controls', () => {
    const source = readFileSync(
      join(cwd(), 'src', 'pages', 'DataReview', 'DataReviewPage.jsx'),
      'utf8',
    );

    expect(source).not.toContain('api.getAiProviders');
    expect(source).not.toContain('api.forwardRawRecordsToAi');
    expect(source).not.toContain('crawler-ai-base-url');
    expect(source).not.toContain('crawler-ai-provider-id');
    expect(source).not.toContain('localhost:8003');
    expect(source).not.toContain('AI-admin');
  });
});
