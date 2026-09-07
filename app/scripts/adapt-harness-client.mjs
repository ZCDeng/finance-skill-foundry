#!/usr/bin/env node
/** A deliberately pinned presentation/input adapter. No prompt or stream protocol fork. */
import {createHash} from 'node:crypto';
import {readFileSync, writeFileSync, existsSync, mkdirSync, copyFileSync} from 'node:fs';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
const APP = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const digest = (data) => createHash('sha256').update(data).digest('hex');
export const STOCK = {
  layout: '16f001f89a9bc19c54cfa90e37cf52e191113af0abe5efd593e57d7ab30060ad',
  conversation: 'fe448ef7e0b1f3e7713dadfc7eff56b9f80d103a2111dfe69c1735ffd0196d61',
  'settings-general': '9298ac5b087056555498550e0e0e6dd9d3202dce48bb07b2a2c4bfeed1d63da5',
  sidebar: '719693c401e7175e73f50e8021d918b2829a602fbd09761a6ef39d055c53460a',
};
function once(source, old, next) {
  if (source.split(old).length !== 2) throw new Error('client adapter anchor drift: ' + old.slice(0, 80));
  return source.replace(old, next);
}
export function adaptSource(name, original) {
  if (digest(original) !== STOCK[name]) throw new Error('Unsupported stock client: ' + name);
  let source = original;
  if (name === 'layout') {
    const start = source.indexOf('\t\tfunction computeColumns(');
    const end = source.indexOf('\n\t\t//#endregion', start);
    source = source.slice(0, start) + `\t\tfunction computeColumns(viewport, sidebar, details) {
      return {sidebar: 0, center: Math.max(0, viewport), details: details === 0 ? 0 : Math.max(0, viewport)};
    }` + source.slice(end);
    source = once(source, 'const colsRef = (0, react.useRef)(cols);', `const colsRef = (0, react.useRef)(cols);
      (0, react.useEffect)(() => {
        if (!cols.details) return;
        const previous = document.activeElement;
        const panel = frameRef.current?.querySelector('.pI_x6G_detailsCol');
        const timer = setTimeout(() => panel?.querySelector('button')?.focus(), 0);
        const key = event => { if (event.key === 'Escape') { event.preventDefault(); actions.closeDetails(); } };
        panel?.addEventListener('keydown', key);
        return () => { clearTimeout(timer); panel?.removeEventListener('keydown', key); if (previous?.isConnected) previous.focus({preventScroll:true}); };
      }, [cols.details, actions]);`);
    source = once(source, 'ref: frameRef,', 'ref: frameRef,\n        "data-foundry-frame": true,');
    source = once(source, '!sidebarCollapsed && (0, react_jsx_runtime.jsx)(DragHandle,', 'false && (0, react_jsx_runtime.jsx)(DragHandle,');
    source = once(source, 'cols.details > 0 && (0, react_jsx_runtime.jsx)(DragHandle,', 'false && (0, react_jsx_runtime.jsx)(DragHandle,');
    const css = readFileSync(join(APP, 'harness-client/compact.css'), 'utf8');
    source += `\n;(() => {window.__fndRailArmed = true;const style=document.createElement('style');style.dataset.foundryCompact='1';style.textContent=${JSON.stringify(css)};document.head.appendChild(style);})();\n`;
  }
  if (name === 'sidebar') {
    const start = source.indexOf('\t\tfunction SidebarRoot(');
    const end = source.indexOf('\n\t\t//#endregion', start);
    source = source.slice(0, start) + `\t\tfunction SidebarRoot({ renderSlot }) {
      return (0, react_jsx_runtime.jsx)('div', {'data-foundry-settings': true, children: renderSlot('sidebar.settings', {wide: false})});
    }` + source.slice(end);
  }
  if (name === 'conversation') {
    // Keep the native title/lineage/actions/log slots intact, but put their
    // existing React tree behind a compact, keyboard-accessible disclosure.
    source = once(source,
      'children: !hideChrome && (0, react_jsx_runtime.jsxs)(react_jsx_runtime.Fragment, { children: [(0, react_jsx_runtime.jsxs)("div", {',
      `children: !hideChrome && (0, react_jsx_runtime.jsxs)(react_jsx_runtime.Fragment, { children: [(0, react_jsx_runtime.jsxs)("details", {
        "data-foundry-session-details": true,
        onKeyDown: event => { if (event.key === 'Escape') { event.preventDefault(); event.currentTarget.open = false; event.currentTarget.querySelector('summary')?.focus(); } },
        children: [(0, react_jsx_runtime.jsx)("summary", {children: "会话信息"}), (0, react_jsx_runtime.jsxs)("div", {`);
    source = once(source,
      '\t\t\t\t}), tabs.length > 1 && (0, react_jsx_runtime.jsx)("div", {',
      '\t\t\t\t})] }), tabs.length > 1 && (0, react_jsx_runtime.jsx)("div", {');
    // Observe native admission only after its stale-attempt guard; never alter
    // the transaction, default sink, permissions, queue, or error behavior.
    source = once(source, 'var InputMachine = class {', 'var InputMachine = class {\n      foundryId = crypto.randomUUID();\n      foundryAdmission;');
    source = once(source, 'if (this.phase !== "submitting" || flight === void 0 || flight.attempt.seq !== ev.attempt.seq) return [];', 'if (this.phase !== "submitting" || flight === void 0 || flight.attempt.seq !== ev.attempt.seq) return [];\n        this.foundryAdmission = {seq: ev.attempt.seq, ok: ev.ok, message: ev.message ?? ev.outcome?.text};');
    source = once(source, 'if (this.phase !== "adjudicating" || this.inflight?.attempt.seq !== attempt.seq) return [];', 'if (this.phase !== "adjudicating" || this.inflight?.attempt.seq !== attempt.seq) return [];\n        this.foundryAdmission = {seq: attempt.seq, ok: false, message};');
    source = once(source, 'this.inflight = void 0;\n\t\t\t\tthis.phase = "plain";\n\t\t\t\treturn [];\n\t\t\t}\n\t\t\tonAdjudicationFailed', 'this.foundryAdmission = {seq: attempt.seq, ok: true};\n        this.inflight = void 0;\n\t\t\t\tthis.phase = "plain";\n\t\t\t\treturn [];\n\t\t\t}\n\t\t\tonAdjudicationFailed');
    const helper = readFileSync(join(APP, 'harness-client/bridge.js'), 'utf8');
    source = once(source, 'const composerBlocks = new ComposerBlockRegistry();', `const composerBlocks = new ComposerBlockRegistry();\n${helper}\ninstallFoundryEmbeddedBridge(ctx, sessions, inputHub, composerBlocks);`);
    source = once(source, 'hero && (0, react_jsx_runtime.jsx)(HeroGlow, { className: ConversationRoot_module_css_default.heroGlow }),', 'null,');
    source = once(source, 'hero && (0, react_jsx_runtime.jsx)(HeroShell, {\n\t\t\t\t\t\tt,\n\t\t\t\t\t\trenderSlot\n\t\t\t\t\t}),', `hero && (0, react_jsx_runtime.jsx)('p', {'data-foundry-empty': true, children: '从一个财务问题开始。资料、计算和结论会保留在当前任务。'}),`);
    source = once(source, 'hero && heroWorkspaceRow,', 'null,');
    source = once(source, '"placeholder.hero": "描述你想要构建的内容"', '"placeholder.hero": "描述你想分析的财务问题"');
    source = once(source, '"placeholder.hero": "Describe what you want to build"', '"placeholder.hero": "Describe your financial question"');
  }
  return source;
}
export function adaptClient(stage, {check = false} = {}) {
  const originals = join(stage, '.foundry-client-stock');
  const manifestPath = join(originals, 'manifest.json');
  const manifest = existsSync(manifestPath) ? JSON.parse(readFileSync(manifestPath, 'utf8')) : {};
  for (const name of Object.keys(STOCK)) {
    const target = join(stage, 'node_modules/@deepseek-ai/dsh-client-ui-' + name + '/lib/client.js');
    const saved = join(originals, name + '.js');
    const current = readFileSync(target, 'utf8');
    const original = digest(current) === STOCK[name] ? current : readFileSync(saved, 'utf8');
    const adapted = adaptSource(name, original);
    if (check) {
      if (current !== adapted) throw new Error('Client adapter missing or stale: ' + name);
    } else {
      if (current !== original && current !== adapted && digest(current) !== manifest[name]?.output) throw new Error('Refusing to overwrite modified client: ' + name);
      mkdirSync(originals, {recursive:true});
      writeFileSync(saved, original);
      writeFileSync(target, adapted);
      manifest[name] = {stock: STOCK[name], output: digest(adapted)};
      writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + '\n');
    }
  }
  const sourceFont = join(APP, 'src/assets/fonts/noto-sans-sc/NotoSansSC-variable.woff2');
  const targetFont = join(stage, 'assets/fonts/NotoSansSC-variable.woff2');
  if (check) {
    if (!existsSync(targetFont) || digest(readFileSync(targetFont)) !== digest(readFileSync(sourceFont))) throw new Error('Native offline font missing or stale');
  } else {
    mkdirSync(dirname(targetFont), {recursive:true});
    copyFileSync(sourceFont, targetFont);
  }
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  adaptClient(join(APP, 'extra/dsh'), {check: process.argv.includes('--check')});
  console.log('Embedded client adapter verified');
}
