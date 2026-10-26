import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const components = new Map();
let plugin;
const jsx = (type, props) => ({ type, props });
const context = {
  window: { __fndRailArmed: true, __ModuleLoader__: { load: definition => {
    plugin = definition.factory(name => {
      assert.equal(name, 'react/jsx-runtime');
      return { jsx, jsxs: jsx };
    });
  } } },
};
vm.runInNewContext(readFileSync(new URL('../dsh-plugin/client.js', import.meta.url), 'utf8'), context);
plugin.apply({
  get: () => ({ registerSource: () => () => {} }),
  effect: fn => fn(),
  slots: {
    inject: (_name, fn) => { const result = fn(); if (result?.next) for (const _ of result) {} },
    register: (slot, component) => components.set(slot.key || slot.name, component),
  },
});
const render = components.get('save_explanation_draft');
assert.equal(typeof render, 'function');
const text = '已保存财务解释。\n' + '这是有明确来源与限制的最终答复；'.repeat(30);
const delivery = {
  schema_version: 1, status: 'verified', channel: 'tool/result', final_response: text,
  final_response_sha256: createHash('sha256').update(text).digest('hex'),
  bindings: { session_id: 'session', request_key: 'request', call_id: 'call', task_id: 'task',
    draft_id: 'draft', draft_content_hash: 'a'.repeat(64), receipt_id: 'receipt',
    requirements_id: 'requirements', completion_status: 'complete' },
};
const block = { kind: 'tool-result', isError: false, content: [{ type: 'text', text }],
  meta: { final_delivery: delivery } };
function visible(node) {
  if (node == null || typeof node === 'boolean') return '';
  if (typeof node !== 'object') return String(node);
  if (Array.isArray(node)) return node.map(visible).join('');
  const children = node.props?.children;
  if (node.type === 'details' && !node.props.open) {
    return visible([children].flat().find(child => child?.type === 'summary'));
  }
  return visible(children);
}
const reports = [];
for (const status of ['complete', 'awaiting_input', 'needs_review', 'awaiting_manager', 'needs_requirements']) {
  const current = structuredClone(block);
  current.meta.final_delivery.bindings.completion_status = status;
  assert.ok(visible(render({ toolName: 'save_explanation_draft', block: current })).includes(text));
  reports.push(status);
}
const invalid = {
  pending: value => { delete value.kind; },
  missing_marker: value => { delete value.meta.final_delivery; },
  unverified: value => { value.meta.final_delivery.status = 'unverified'; },
  wrong_version: value => { value.meta.final_delivery.schema_version = 2; },
  wrong_channel: value => { value.meta.final_delivery.channel = 'assistant/message'; },
  different_text: value => { value.content[0].text = 'stale'; },
  extra_content: value => { value.content.push({ type: 'text', text: 'extra' }); },
  missing_hash: value => { delete value.meta.final_delivery.final_response_sha256; },
  missing_binding: value => { delete value.meta.final_delivery.bindings.receipt_id; },
  nonterminal: value => { value.meta.final_delivery.bindings.completion_status = 'repair_available'; },
};
for (const [name, change] of Object.entries(invalid)) {
  const current = structuredClone(block); change(current);
  assert.ok(!visible(render({ toolName: 'save_explanation_draft', block: current })).includes(text), name);
  reports.push(name);
}
assert.ok(!visible(render({ toolName: 'run_metric', block })).includes(text));
const error = render({ toolName: 'save_explanation_draft', block: { ...block, isError: true } });
assert.equal(error.type, 'details');
assert.equal(error.props.open, true);
console.log(JSON.stringify({ passed: true, checks: reports.length + 2, provider_calls: 0 }));
