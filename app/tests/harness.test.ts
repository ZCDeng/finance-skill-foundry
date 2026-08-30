import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import {
  LineBuffer,
  PRESET_BY_INTENT,
  ROLE_BY_INTENT,
  harnessArgs,
  harnessEnv,
  harnessUrlFrom,
  rpcBody,
  rpcUrl,
  rpcValue,
} from '../electron/harness/boot.js';
import { HEADER_HEIGHT, TASK_BAR_HEIGHT, viewBounds } from '../electron/harness/bounds.js';
import { CHAT_STORE_PREFIX, SESSION_SELECTION_KEY, chatStoreKey, followupDraft, handoffScript } from '../electron/harness/handoff.js';

const read = (rel: string) => readFileSync(fileURLToPath(new URL(rel, import.meta.url)), 'utf8');

describe('reading the runtime banner', () => {
  it('takes a loopback URL and nothing else', () => {
    expect(harnessUrlFrom('dsh web: http://127.0.0.1:51823/')).toBe('http://127.0.0.1:51823');
    expect(harnessUrlFrom('dsh web: http://localhost:5173')).toBe('http://localhost:5173');
  });

  it('refuses a banner naming a runtime this app did not start', () => {
    // A port must be present, the host must be loopback, and credentials in the
    // authority are somebody else's server.
    expect(harnessUrlFrom('dsh web: http://10.0.0.4:51823/')).toBeNull();
    expect(harnessUrlFrom('dsh web: https://127.0.0.1:51823/')).toBeNull();
    expect(harnessUrlFrom('dsh web: http://127.0.0.1/')).toBeNull();
    expect(harnessUrlFrom('dsh web: http://user:pw@127.0.0.1:8080/')).toBeNull();
    expect(harnessUrlFrom('starting up')).toBeNull();
  });

  it('does not lose a banner split across two chunks', () => {
    const lines = new LineBuffer();
    expect(lines.push('dsh web: http://12')).toEqual([]);
    expect(lines.push('7.0.0.1:900/\nnext')).toEqual(['dsh web: http://127.0.0.1:900/']);
    expect(lines.flush()).toEqual(['next']);
  });
});

describe('the environment the child gets', () => {
  const scrubbed = harnessEnv(
    {
      PATH: '/usr/bin',
      OPENAI_API_KEY: 'sk-live',
      DEEPSEEK_API_KEY: 'sk-live',
      GITHUB_TOKEN: 'ghp',
      MY_SECRET: 'x',
      AWS_CREDENTIALS: 'x',
      DB_PASSWORD: 'x',
      DSH_HOME: '/somebody/else',
      DSH_PROFILE: 'standard',
      FOUNDRY_TASK: 'stale',
      FOUNDRY_VAR: '/somebody/else/var',
    },
    { home: '/app/harness', varRoot: '/app/var', foundryBin: '/app/foundry' },
  );

  it('hands over no key-shaped name', () => {
    // The child is the process that talks to model providers, and it must not be
    // handed a credential its operator never gave it. Keys reach the harness
    // through its own settings, where they can be seen and removed.
    for (const name of Object.keys(scrubbed)) {
      expect(name, name).not.toMatch(/(^|_)(API_?KEY|TOKEN|SECRET|PASSWORD|CREDENTIALS?)($|_)/i);
    }
    expect(scrubbed.PATH).toBe('/usr/bin');
  });

  it('drops an ambient DSH_ rather than letting it choose the composition', () => {
    // Those select profiles, homes and tool modes -- including which agent preset
    // is the default, which is this product's fence.
    expect(scrubbed.DSH_PROFILE).toBeUndefined();
    expect(scrubbed.DSH_HOME).toBe('/app/harness');
  });

  it('sets the store from this app and refuses to inherit a task', () => {
    // One harness process serves every session and every task, so a process-wide
    // task would bind them all to whichever one happened to be open. The CLI's
    // resolution chain covers it from the window's own back-pointer.
    expect(scrubbed.FOUNDRY_VAR).toBe('/app/var');
    expect(scrubbed.FOUNDRY_BIN).toBe('/app/foundry');
    expect(scrubbed.FOUNDRY_TASK).toBeUndefined();
  });
});

describe('the button decides the preset', () => {
  it('opens a follow-up on f3 and nothing else', () => {
    // KTD7. The preset rides `session.create`, is recorded on the session's
    // creation header, and cannot be widened later by anything the model does.
    expect(PRESET_BY_INTENT.followup).toBe('f3');
    expect(PRESET_BY_INTENT.period).toBe('period');
    expect(ROLE_BY_INTENT.followup).toBe('followup');
  });

  it('agrees with the presets the kit installs', () => {
    // `period` and `f3` are foundry's own; `standard` is upstream's, and
    // authoring runs on it deliberately -- F1 has no locked window to read
    // around and wants the editor that preset carries.
    const declared = JSON.parse(read('../../dsh-plugin/package.json')).dsh.foundry.presets.ids;
    expect(declared).toContain(PRESET_BY_INTENT.period);
    expect(declared).toContain(PRESET_BY_INTENT.followup);
    expect(declared).not.toContain(PRESET_BY_INTENT.author);
  });

  it('gives the runtime the node flag its reload chain requires', () => {
    // A node flag, so it goes before the entry. Without it the `web` profile's
    // HMR row refuses to construct under Electron-as-Node and the whole plugin
    // tree fails to load -- which is a workbench that never starts, not a
    // degraded one.
    expect(harnessArgs('/x/bin.js')[0]).toBe('--expose-internals');
    expect(harnessArgs('/x/bin.js')[1]).toBe('/x/bin.js');
  });

  it('names the runtime entry and asks the OS for a port', () => {
    // A fixed port would collide with whatever else is listening and would make
    // two copies of this app fight.
    expect(harnessArgs('/x/bin.js')).toEqual([
      '--expose-internals',
      '/x/bin.js',
      'web',
      '--host',
      '127.0.0.1',
      '--port',
      '0',
      '--no-open',
    ]);
  });
});

describe('the hand-off', () => {
  it('uses the storage cells the installed runtime reads', () => {
    // Coupling to keys upstream owns, so a rename there has to become a red test
    // rather than a hand-off that silently does nothing.
    const install = process.env.FOUNDRY_DSH_INSTALL;
    if (!install) return;
    const client = readFileSync(
      `${install}/node_modules/@deepseek-ai/dsh-client-runtime/lib/client.js`,
      'utf8',
    );
    expect(client).toContain(SESSION_SELECTION_KEY);
    const conversation = readFileSync(
      `${install}/node_modules/@deepseek-ai/dsh-client-ui-conversation/lib/client.js`,
      'utf8',
    );
    expect(conversation).toContain(CHAT_STORE_PREFIX);
  });

  it('quotes every value it writes into the page', () => {
    // A window id or a pasted question carrying a quote must not be able to end
    // the string it is written into.
    const script = handoffScript('a"b', 'say "hi"\n</script>');
    expect(script).toContain(JSON.stringify('a"b'));
    expect(script).toContain(JSON.stringify('say "hi"\n</script>'));
    expect(script).toContain(JSON.stringify(chatStoreKey('a"b')));
  });

  it('parks a draft rather than sending one', () => {
    // There is no server verb that parks text: `session.prompt` wakes the driver
    // and opens a turn either way. A follow-up is the operator's to send, after
    // they have seen it.
    expect(handoffScript('s1', '')).not.toContain(CHAT_STORE_PREFIX);
    expect(read('../electron/harness/host.ts')).not.toContain('session.prompt');
  });

  it('seeds the two facts a model cannot work out', () => {
    const draft = followupDraft({ windowId: 'w1', briefSha: 'ab'.repeat(32) });
    expect(draft).toContain('w1');
    expect(draft).toContain('ab'.repeat(32));
    expect(followupDraft({ windowId: 'w1', briefSha: null })).not.toContain('那一版');
  });

  it('posts to the path the gateway serves, not just to /api', () => {
    // Measured against a running runtime: the envelope alone at `/api` answers
    // `not found`. The first version of this did exactly that, and the tests
    // passed because they only ever checked the envelope.
    expect(rpcUrl('http://127.0.0.1:52361', 'session.create')).toBe(
      'http://127.0.0.1:52361/api/session.create',
    );
    expect(read('../electron/harness/host.ts')).toContain('rpcUrl(origin, method)');
  });

  it('reports the refusal the runtime actually sent', () => {
    // Measured shapes, both of them. A refusal is nested inside `result`, and
    // reading a top-level `error` finds nothing -- which turns "these are the
    // presets that exist" into "no session id".
    expect(
      rpcValue('session.create', {
        type: 'server-response',
        result: { ok: true, value: { sessionId: 'session-1', agentPreset: 'f3' } },
      }),
    ).toEqual({ sessionId: 'session-1', agentPreset: 'f3' });

    expect(() =>
      rpcValue('session.create', {
        type: 'server-response',
        result: {
          ok: false,
          error: { code: 'agent-preset-not-found', message: 'preset "nope" not found (available: standard, period, f3)' },
        },
      }),
    ).toThrow(/available: standard, period, f3/);
  });

  it('sends a well-formed RPC envelope', () => {
    expect(JSON.parse(rpcBody('session.create', { agentPreset: 'f3' }))).toEqual({
      type: 'client-request',
      rpcId: 'fnd-session.create',
      method: 'session.create',
      payload: { agentPreset: 'f3' },
    });
  });
});

describe('the rectangle the page gets', () => {
  it('leaves the header and the task bar visible', () => {
    expect(viewBounds({ width: 1280, height: 860 })).toEqual({
      x: 0,
      y: HEADER_HEIGHT + TASK_BAR_HEIGHT,
      width: 1280,
      height: 860 - HEADER_HEIGHT - TASK_BAR_HEIGHT,
    });
  });

  it('never hands back an inverted rectangle', () => {
    // A window dragged shorter than its own chrome. Electron accepts a negative
    // height and draws a view over the strip that was meant to stay visible.
    expect(viewBounds({ width: 400, height: 10 }).height).toBe(0);
  });

  it('agrees with the stylesheet about how tall the strips are', () => {
    // Main positions the view in window coordinates, so these two numbers have
    // to be the same number in two languages.
    const css = read('../src/components/components.css');
    const taskbar = css.slice(css.indexOf('.fnd-taskbar {'));
    expect(taskbar.slice(0, taskbar.indexOf('}'))).toContain(`height: ${TASK_BAR_HEIGHT}px;`);
    expect(read('../src/styles/tokens.css')).toContain(`--fnd-header-height: ${HEADER_HEIGHT}px;`);
    const head = css.slice(css.indexOf('.fnd-head {'));
    expect(head.slice(0, head.indexOf('}'))).toContain('height: var(--fnd-header-height);');
  });
});
