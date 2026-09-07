import {readFileSync, existsSync} from 'node:fs';
import {resolve} from 'node:path';
import {describe, expect, it} from 'vitest';
// @ts-expect-error Build tooling intentionally stays dependency-free JavaScript.
import {adaptSource} from '../scripts/adapt-harness-client.mjs';
const stock = (name: string) => {
  const saved = resolve('extra/dsh/.foundry-client-stock', `${name}.js`);
  return readFileSync(existsSync(saved) ? saved : resolve(`extra/dsh/node_modules/@deepseek-ai/dsh-client-ui-${name}/lib/client.js`), 'utf8');
};
describe('checked native compact adapter', () => {
  it.each(['layout', 'sidebar', 'conversation'])('replays %s against exact pinned source and rejects drift', name => {
    const source = stock(name);
    const adapted = adaptSource(name, source);
    expect(() => new Function(adapted)).not.toThrow();
    expect(() => adaptSource(name, source + ' ')).toThrow('Unsupported stock');
  });
  it.each([400, 460])('keeps details reachable at %ipx without a sidebar rail', width => {
    const source = adaptSource('layout', stock('layout'));
    const body = source.slice(source.indexOf('function computeColumns('), source.indexOf('\n\t\t//#endregion', source.indexOf('function computeColumns(')));
    const columns = new Function(body + '; return computeColumns;')();
    expect(columns(width, 280, 340)).toEqual({sidebar: 0, center: width, details: width});
    expect(columns(width, 280, 0).details).toBe(0);
    expect(source).toContain('actions.closeDetails()');
  });
  it('wraps the original session title/actions/log tree without replacing native callbacks', () => {
    const original = stock('conversation');
    const start = original.indexOf('className: ConversationRoot_module_css_default.titleRow,');
    const end = original.indexOf('}), tabs.length > 1', start);
    expect(start).toBeGreaterThan(-1);
    expect(end).toBeGreaterThan(start);
    const originalChildren = original.slice(start, end);
    const adapted = adaptSource('conversation', original);
    expect(adapted).toContain(originalChildren);
    expect(adapted).toContain('"data-foundry-session-details": true');
  });
  it('preserves settings and native composer chain, while removing alternative task navigation', () => {
    const sidebar = adaptSource('sidebar', stock('sidebar'));
    const root = sidebar.slice(sidebar.indexOf('function SidebarRoot('), sidebar.indexOf('\n\t\t//#endregion', sidebar.indexOf('function SidebarRoot(')));
    expect(root).toContain("renderSlot('sidebar.settings'");
    expect(root).not.toContain('sidebar.workspaces');
    const conversation = adaptSource('conversation', stock('conversation'));
    expect(conversation).toContain('installFoundryEmbeddedBridge(ctx, sessions, inputHub, composerBlocks)');
    expect(conversation).toContain('renderSlotChain("conversation.composer"');
    expect(conversation).toContain('const inert = sessionId === void 0 || hero && chipTitle === void 0;');
  });
});
