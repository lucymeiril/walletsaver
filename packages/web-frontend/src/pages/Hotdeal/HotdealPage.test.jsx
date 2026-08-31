import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(__dirname, 'HotdealPage.jsx'), 'utf8');

describe('HotdealPage regressions', () => {
  it('does not notify parent comment count from inside setComments updater', () => {
    expect(source).not.toMatch(/setComments\s*\(\s*prev\s*=>\s*\{[\s\S]*onCommentCountChange/);
    expect(source).toContain('onCommentCountChange?.(item.id, comments.length)');
  });

  it('sends backend vote aliases and handles pending modal votes', () => {
    expect(source).toContain("if (type === 'cold') return 'not';");
    expect(source).toContain("disabled={isVotePending}");
    expect(source).toContain("response.status === 429");
  });
});
