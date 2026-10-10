import {readFileSync} from 'node:fs';
import {describe, expect, it} from 'vitest';
import {CARD_ACTION_MARKER, cardNonceScript, readCardAction} from '../electron/harness/cardAction.js';

const nonce = 'a'.repeat(32);
const task = 'b'.repeat(32);
const run = 'c'.repeat(32);
const line = (value: unknown) => CARD_ACTION_MARKER + JSON.stringify(value);
const pin = {kind: 'figure', title: '集团距生死线', run_id: run, select: {match: {entity: '集团'}, column: 'value'}};

describe('a click on a card in the conversation', () => {
  it('reads 打开结果 and 钉到看板 stamped with this window nonce', () => {
    expect(readCardAction(line({nonce, action: 'open', task_id: task, kind: 'analysis', run_id: run, analysis_id: 'an-1'}), nonce))
      .toEqual({action: 'open', taskId: task, kind: 'analysis', runId: run, analysisId: 'an-1'});
    expect(readCardAction(line({nonce, action: 'open', task_id: task, kind: 'collection', run_id: run}), nonce))
      .toEqual({action: 'open', taskId: task, kind: 'collection', runId: run});
    expect(readCardAction(line({nonce, action: 'pin', task_id: task, card: pin}), nonce)).toEqual({action: 'pin', taskId: task, card: pin});
    // A 倒推 or 敏感性 card pins as the what-if it is; the board's own save checks what it works back to.
    const goal = {kind: 'goal', title: '回到生死线', run_id: run, select: {match: {entity: '集团', scenario: '本期'}, goal: 'collection', target: '92%'}};
    expect(readCardAction(line({nonce, action: 'pin', task_id: task, card: goal}), nonce)).toEqual({action: 'pin', taskId: task, card: goal});
    expect(readCardAction(line({nonce, action: 'open', task_id: task, kind: 'analysis', run_id: run, analysis_id: '../x'}), nonce))
      .toMatchObject({analysisId: null});
  });

  it('ignores every line that is not one this window made possible', () => {
    const fine = {nonce, action: 'pin', task_id: task, card: pin};
    for (const bad of [
      'hello', `${CARD_ACTION_MARKER}{`, line({...fine, nonce: 'other'}), line({...fine, nonce: undefined}), line({...fine, task_id: 'x'}),
      line({...fine, action: 'accept'}), line({...fine, card: {...pin, kind: 'scenario'}}), line({...fine, card: {...pin, title: ' '}}),
      line({...fine, card: {...pin, title: 'x'.repeat(61)}}), line({...fine, card: {...pin, title: 'a\nb'}}), line({...fine, card: {...pin, run_id: 'r'}}),
      line({...fine, card: {...pin, select: {column: 'value'}}}), line({...fine, card: {...pin, select: {match: {entity: 3}}}}),
      line({nonce, action: 'open', task_id: task, kind: 'chart', run_id: run}), line({nonce, action: 'open', task_id: task, kind: 'analysis', run_id: 'x'}),
      `x${line(fine)}`, line(fine) + ' '.repeat(20_000), line([fine]),
    ]) expect(readCardAction(bad, nonce)).toBeNull();
    expect(readCardAction(line(fine), '')).toBeNull();
    expect(readCardAction(42, nonce)).toBeNull();
  });

  it('puts the nonce in the page, and the cards write the marker this window reads', () => {
    const page: Record<string, unknown> = {};
    new Function('window', cardNonceScript(nonce))(page);
    expect(page.__foundryCardNonce).toBe(nonce);
    expect(readFileSync(new URL('../../dsh-plugin/client.js', import.meta.url), 'utf8')).toContain(`'${CARD_ACTION_MARKER}'`);
  });
});
