import { describe, expect, it } from 'vitest';
import { errorText, friendlyError, scenarioLabel, withoutIdentifiers } from '../src/views/analysis/glossary.js';

describe('friendlyError', () => {
  it('says what the manager should do and keeps the engine sentence as a hint', () => {
    const text = friendlyError('requirements update must reference the latest version');
    expect(text.startsWith('范围在别处已经更新过')).toBe(true);
    expect(text).toContain('（系统提示：requirements update must reference the latest version）');
  });

  it('names the conflicting scope field in words', () => {
    expect(friendlyError('requirement periods conflict with scope.period')).toContain('共同期间与逐项期间冲突');
  });

  it('does not translate a sentence twice', () => {
    const once = friendlyError('dataset integrity check failed');
    expect(friendlyError(once)).toBe(once);
  });

  it('leaves an unknown sentence as written, minus identifiers', () => {
    const id = 'a'.repeat(32);
    expect(friendlyError(`资料 ${id} 已归档`)).toBe('资料 （编号已省略） 已归档');
    expect(withoutIdentifiers(`sha256:${'b'.repeat(64)}`)).toBe('（摘要已省略）');
  });

  it('reads Error and non-Error failures alike', () => {
    expect(errorText(new Error('workbook output already exists'))).toContain('已经存在');
    expect(errorText('')).toContain('请重试一次');
  });
});

describe('scenarioLabel', () => {
  it('knows the engine scenario keys and their period suffixes', () => {
    expect(scenarioLabel('actual_ytd')).toBe('累计实际');
    expect(scenarioLabel('budget_2026_08')).toBe('预算');
    expect(scenarioLabel('something_else')).toBe('something_else');
  });
});
