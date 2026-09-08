import {readFileSync, existsSync} from 'node:fs';
import {resolve} from 'node:path';
import {describe, expect, it} from 'vitest';
// @ts-expect-error Build tooling intentionally stays dependency-free JavaScript.
import {adaptSource} from '../scripts/adapt-harness-client.mjs';
const stockPath = (name: string) => name === 'session-log-export'
  ? 'extra/dsh/node_modules/@deepseek-ai/dsh-session-log-export/lib/client.js'
  : `extra/dsh/node_modules/@deepseek-ai/dsh-client-ui-${name}/lib/client.js`;
const stock = (name: string) => {
  const saved = resolve('extra/dsh/.foundry-client-stock', `${name}.js`);
  return readFileSync(existsSync(saved) ? saved : resolve(stockPath(name)), 'utf8');
};
describe('checked native compact adapter', () => {
  it.each(['layout', 'sidebar', 'conversation', 'session-log-export'])('replays %s against exact pinned source and rejects drift', name => {
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
    expect(adapted).toContain('children: "对话工具"');
    expect(adapted).not.toContain('children: "会话信息"');
    expect(adapted).toContain('\"data-foundry-session-panel\": true');
    expect(adapted).toContain('\"data-foundry-session-help\": true');
    expect(adapted).toContain('查看当前对话与分析方式，必要时导出排查日志。');
    const compactCss = readFileSync(resolve('harness-client/compact.css'), 'utf8');
    expect(compactCss).toContain('--foundry-session-disclosure:var(--fnd-disclosure, #426786)');
    expect(compactCss).toContain('--foundry-session-disclosure:var(--fnd-disclosure, #a4bfd5)');
    expect(compactCss).not.toContain('::before { content');
  });

  it('localizes the session log export action without replacing the request callback', () => {
    const original = stock('session-log-export');
    const header = original.indexOf('function SessionLogDownloadHeaderAction');
    expect(header).toBeGreaterThan(-1);
    const start = original.indexOf('onClick: () => {', header);
    const end = original.indexOf('},\n\t\t\t\tchildren:', start);
    expect(start).toBeGreaterThan(-1);
    expect(end).toBeGreaterThan(start);
    const originalCallback = original.slice(start, end);
    const adapted = adaptSource('session-log-export', original);
    expect(() => new Function(adapted)).not.toThrow();
    expect(() => adaptSource('session-log-export', original + ' ')).toThrow('Unsupported stock');
    expect(adapted).toContain(originalCallback);
    expect(adapted).toContain('children: "导出排查日志"');
    expect(adapted).toContain('title: "下载当前对话的排查日志"');
    expect(adapted).toContain('"aria-label": "导出排查日志"');
    expect(adapted).not.toContain('children: "Session log"');
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
