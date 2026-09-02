import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { delimiter, join } from 'node:path';
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
import { companionEnv } from '../electron/harness/resources.js';
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

  it('carries the Formulator pointer to the child', () => {
    // The data screen reaches `launch-formulator` from main, which has this. A
    // model calling the same tool inside a session reaches it through the child,
    // and a child stripped of it would report `Data Formulator binary is not
    // installed` in a packaged app that ships one.
    const withDf = harnessEnv(
      {},
      { home: '/h', varRoot: '/v', foundryBin: '/b', formulatorBin: '/A/Resources/formulator/data_formulator' },
    );
    expect(withDf.FOUNDRY_FORMULATOR_BIN).toBe('/A/Resources/formulator/data_formulator');
    // A build with none staged names none, and the kit falls back to PATH.
    expect(harnessEnv({}, { home: '/h', varRoot: '/v', foundryBin: '/b' }).FOUNDRY_FORMULATOR_BIN).toBeUndefined();
  });

  it('sets the store from this app and refuses to inherit a task', () => {
    // One harness process serves every session and every task, so a process-wide
    // task would bind them all to whichever one happened to be open. The CLI's
    // resolution chain covers it from the window's own back-pointer.
    expect(scrubbed.FOUNDRY_VAR).toBe('/app/var');
    expect(scrubbed.FOUNDRY_BIN).toBe('/app/foundry');
    expect(scrubbed.FOUNDRY_TASK).toBeUndefined();
  });

  it("does not pretend to fence the plugin's own Univer gateway", () => {
    // The plugin builds that gateway's environment from an explicit list --
    // `HOME LANG LC_ALL PATH TMPDIR` plus its own three names, read from
    // `lib/index.js` (`gatewayLaunch`) -- so a `UNIVER_ALLOWED_ROOT` set on
    // this child never reaches it. An earlier version set one here and
    // asserted it, which was a fence that measured as present and did nothing.
    // The gateway this app does fence is the one it spawns itself, in
    // `univer.ts`; the plugin's own is denied to the close seat by preset.
    expect(harnessEnv({}, { home: '/h', varRoot: '/v', foundryBin: '/b' }).UNIVER_ALLOWED_ROOT).toBeUndefined();
    expect(read('../electron/harness/boot.ts')).not.toContain('out.UNIVER_ALLOWED_ROOT');
  });

  it('agrees with the installed plugin about what its gateway is allowed to inherit', () => {
    // Coupling to the plugin's launcher, so a release that starts forwarding
    // the whole environment -- and with it a fence this app could set -- turns
    // the sentence above into a red test rather than a stale comment.
    const install = process.env.FOUNDRY_DSH_INSTALL;
    if (!install) return;
    const host = readFileSync(`${install}/node_modules/dsh-univer-office/lib/index.js`, 'utf8');
    expect(host).toContain('["HOME", "LANG", "LC_ALL", "PATH", "TMPDIR"]');
    expect(host).toContain('UNIVER_COLLAB_GATEWAY_PORT: String(port)');
    expect(host).not.toContain('UNIVER_ALLOWED_ROOT');
  });
});

describe('the environment the Univer gateway and its worker get', () => {
  /*
   * A third-party server and a third-party worker this app starts on the
   * operator's behalf, and the three things it enforces are the three the
   * operator accepted (KTD20): the filesystem fence, the process living only
   * while a preview is open, and no model anywhere near it. This file covers
   * the first; the other two are the host's own lifecycle and the preset
   * scopes that already exist.
   */
  it('inherits five names and nothing else, the same five the plugin forwards', async () => {
    // The plugin's own launcher forwards exactly these to the same program.
    // This app's shell has keys, `DSH_*` and `FOUNDRY_*` in it, and none of
    // them is the gateway's business.
    const { gatewayEnv } = await import('../electron/univer.js');
    const env = gatewayEnv(
      {
        PATH: '/usr/bin',
        HOME: '/Users/x',
        LANG: 'zh_CN.UTF-8',
        DEEPSEEK_API_KEY: 'sk-live',
        GITHUB_TOKEN: 'ghp',
        FOUNDRY_VAR: '/v',
        DSH_HOME: '/d',
        UNIVER_ALLOWED_ROOT: '/',
        UNIVER_COLLAB_GATEWAY_PORT: '1',
        UNIVER_RENDER_BROWSER: '/x',
      },
      { port: 9081, viewerRoot: '/b/artifacts/viewer', allowedRoot: '/app/var/tasks/t/artifacts', nodePath: '/stage/node_modules' },
    );
    expect(Object.keys(env).sort()).toEqual([
      'DO_NOT_TRACK',
      'ELECTRON_RUN_AS_NODE',
      'HOME',
      'LANG',
      'NODE_PATH',
      'PATH',
      'UNIVER_ALLOWED_ROOT',
      'UNIVER_COLLAB_GATEWAY_PORT',
      'UNIVER_VIEW_ASSETS_ROOT',
    ]);
    // An inherited `UNIVER_ALLOWED_ROOT=/` would have widened the one boundary
    // the gateway enforces; an inherited port would collide with whatever set it.
    expect(env.UNIVER_ALLOWED_ROOT).toBe('/app/var/tasks/t/artifacts');
    expect(env.UNIVER_COLLAB_GATEWAY_PORT).toBe('9081');
    expect(env.UNIVER_VIEW_ASSETS_ROOT).toBe('/b/artifacts/viewer');
    expect(env.NODE_PATH).toBe('/stage/node_modules');
    expect(env.DO_NOT_TRACK).toBe('1');
    expect(env.ELECTRON_RUN_AS_NODE).toBe('1');
  });

  it("keeps an operator's NODE_PATH behind the bundle's own, for the gateway and the worker alike", async () => {
    // `libsql` and the two native bindings are resolved from the staged
    // `node_modules` the bundle sits in; the plugin sets the same thing for
    // the same reason. The worker reads no `UNIVER_` name at all.
    const { gatewayEnv, workerEnv } = await import('../electron/univer.js');
    const env = gatewayEnv(
      { NODE_PATH: '/theirs' },
      { port: 9080, viewerRoot: '/v', allowedRoot: '/f', nodePath: '/stage/node_modules' },
    );
    expect(env.NODE_PATH).toBe(`/stage/node_modules${delimiter}/theirs`);
    const worker = workerEnv({ PATH: '/usr/bin', UNIVER_ALLOWED_ROOT: '/' }, { nodePath: '/stage/node_modules' });
    expect(Object.keys(worker).sort()).toEqual(['DO_NOT_TRACK', 'ELECTRON_RUN_AS_NODE', 'NODE_PATH', 'PATH']);
  });

  it('names the container by its digest, strictly inside the fence, and the viewer by the container', async () => {
    const { containerPath, fileKey, viewerUrl } = await import('../electron/univer.js');
    const root = '/app/var/tasks/t/artifacts';
    const file = containerPath(root, 'c'.repeat(64));
    // Under a subdirectory, not at the root: the gateway refuses a container
    // whose path *is* the allowed root as well as one outside it.
    expect(file).toBe(join(root, 'preview', `${'c'.repeat(64)}.univer`));
    // `base64url` of the absolute path: what the plugin's `file-api.ts` sends
    // and the gateway's `univerfile-manager.ts` decodes.
    expect(fileKey('/a/b.univer')).toBe(Buffer.from('/a/b.univer', 'utf8').toString('base64url'));
    // The trunk page, the same URL the plugin's `computeFileState` calls `viewerUrl`.
    expect(viewerUrl('http://127.0.0.1:9080', '/a/b.univer')).toBe(
      `http://127.0.0.1:9080/?file=${encodeURIComponent(fileKey('/a/b.univer'))}`,
    );
  });

  it('finds the three artifacts where the bundle keeps them, and says when they are absent', async () => {
    const { gatewayEntry, nodePath, univerStaged, viewerRoot, workerEntry } = await import('../electron/univer.js');
    const layout = { bundleDir: '/stage/node_modules/dsh-univer-office' };
    expect(gatewayEntry(layout)).toBe('/stage/node_modules/dsh-univer-office/artifacts/gateway.cjs');
    expect(viewerRoot(layout)).toBe('/stage/node_modules/dsh-univer-office/artifacts/viewer');
    expect(workerEntry(layout)).toBe('/stage/node_modules/dsh-univer-office/artifacts/unit-content-worker.mjs');
    expect(nodePath(layout)).toBe('/stage/node_modules');
    // A build without the bundle is a build with one fewer button, not a broken one.
    expect(univerStaged({ bundleDir: '/nonexistent' })).toBe(false);
  });

  it('agrees with the installed gateway about its banner, its exit code, its fence and its routes', () => {
    // Every wire shape in `univer.ts` is read from the bundle's bytes. This
    // pins the ones a release could move: the banner the host waits for, the
    // port-in-use exit, the one environment name that is the fence, and the
    // worktree route the snapshot goes through.
    const install = process.env.FOUNDRY_DSH_INSTALL;
    if (!install) return;
    const gateway = readFileSync(`${install}/node_modules/dsh-univer-office/artifacts/gateway.cjs`, 'utf8');
    expect(gateway).toContain('[dsh-univer-gateway] listening on http://127.0.0.1:');
    expect(gateway).toContain('var GATEWAY_PORT_IN_USE_EXIT_CODE = 98;');
    expect(gateway).toContain('env.UNIVER_ALLOWED_ROOT');
    expect(gateway).toContain('univerfile is outside the allowed root');
    expect(gateway).toContain('viewUrl: `/?file=${encodeURIComponent(key)}`');
    expect(gateway).toContain("sub2[0] === \"units\" && method2 === \"POST\"");
    const host = readFileSync(`${install}/node_modules/dsh-univer-office/lib/index.js`, 'utf8');
    expect(host).toContain('operation: "import", sourcePath, unitType: unitType3(kind)');
    expect(host).toContain('`${gateway}/?file=${encodeURIComponent(fileKeyOf(file))}`');
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

describe('two embedded pages, one rectangle', () => {
  it('places both from the screen name, so a switch cannot stack them', () => {
    // Neither page is part of the document, so React unmounting a component
    // hides nothing. One handler decides which rectangle is real, and it places
    // both -- a handler that only showed the incoming one would leave the
    // outgoing page on top of it.
    const register = readFileSync(
      fileURLToPath(new URL('../electron/ipc/register.ts', import.meta.url)),
      'utf8',
    );
    const block = register.slice(register.indexOf('CHANNELS.paneVisible'));
    expect(block).toContain("panes.host.place(window, name === 'workbench')");
    expect(block).toContain("panes.formulator.place(window, name === 'formulator')");
  });
});

describe('wiring failures reach the screen', () => {
  it('names a consequence for every step, in the operator\'s terms', async () => {
    const { WIRING_CONSEQUENCE } = await import('../electron/harness/wiring.js');
    expect(Object.keys(WIRING_CONSEQUENCE).sort()).toEqual(['attach', 'plugin', 'presets']);
    // The step names are the code's. What an operator needs is which capability
    // is missing, so each one has to say that rather than repeat the step.
    for (const [step, text] of Object.entries(WIRING_CONSEQUENCE)) {
      expect(text.length, step).toBeGreaterThan(20);
      expect(text, step).not.toContain(step);
    }
  });

  it('reports the state without starting the harness', () => {
    // The old handler awaited `host.start()`, so the one call a screen makes to
    // find out whether the wiring failed either hung on a start that was never
    // going to happen or reported that timeout instead of the reason.
    const register = read('../electron/ipc/register.ts');
    const handler = register.slice(register.indexOf('CHANNELS.harnessStatus'));
    const body = handler.slice(0, handler.indexOf('ipcMain.handle', 1));
    expect(body).toContain('harness.host.origin()');
    expect(body).not.toContain('host.start()');
  });

  it('carries the step out of the catch rather than only logging it', () => {
    const main = read('../electron/main.ts');
    const block = main.slice(main.indexOf('let step: WiringStep'), main.indexOf('createWindow();'));
    expect(block).toContain("wiring = { state: 'failed', step, message }");
    // Kept as well as surfaced: one sentence on screen, the full message where
    // it can be read.
    expect(block).toContain('console.error');
  });

  it('draws the runtime own message under the consequence, not instead of it', () => {
    // The consequence says what is missing; the message says which file. Only
    // the second makes it fixable.
    const view = read('../src/views/Workbench.tsx');
    const panel = view.slice(view.indexOf('export function WiringTrouble'));
    const body = panel.slice(0, panel.indexOf('\n}'));
    expect(body.indexOf('status.consequence')).toBeLessThan(body.indexOf('status.wiring.message'));
    expect(body).toContain("status.wiring.state !== 'failed'");
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

describe('the runtime own developer notice', () => {
  it('reads all three constants out of the shipped bundle', async () => {
    // Read rather than restated, so a pinned runtime carrying a *different*
    // notice gets that one's version written instead of a stale literal.
    const { readNotice, noticePatch } = await import('../electron/harness/notice.js');
    const notice = readNotice(new URL('../extra/dsh', import.meta.url).pathname);
    if (!notice) return; // the staged runtime is not on this machine
    expect(notice.namespace).toBe('ui-onboarding');
    expect(notice.field).toBe('welcomeNoticeVersion');
    expect(notice.version).toMatch(/^\d{4}-\d{2}-\d{2}/);
    expect(noticePatch(notice)).toEqual({
      ns: 'ui-onboarding',
      patch: { welcomeNoticeVersion: notice.version },
    });
  });

  it('suppresses nothing when it cannot read the bundle', async () => {
    // The fallback is that an operator reads a notice meant for Harness
    // developers and presses Continue. That is visible and harmless; a guessed
    // value written into somebody's settings is neither.
    const { readNotice } = await import('../electron/harness/notice.js');
    expect(readNotice('/nonexistent')).toBeNull();
  });

  it('refuses a bundle that defines a constant more than once', async () => {
    // The whole method is reading a literal out of somebody else's build
    // output. One definition is a fact; two is a bundle whose shape this does
    // not understand, and picking either would be a guess written into an
    // operator's settings.
    const { mkdtempSync, mkdirSync, writeFileSync } = await import('node:fs');
    const { tmpdir } = await import('node:os');
    const { join } = await import('node:path');
    const { readNotice } = await import('../electron/harness/notice.js');

    const root = mkdtempSync(join(tmpdir(), 'fnd-notice-'));
    const dir = join(root, 'node_modules', '@deepseek-ai', 'dsh-client-ui-settings-models', 'lib');
    mkdirSync(dir, { recursive: true });
    const one =
      'SETTINGS_NAMESPACE = "ui-onboarding";\n' +
      'WELCOME_NOTICE_ACK_FIELD = "welcomeNoticeVersion";\n' +
      'WELCOME_NOTICE_VERSION = "2026-08-13.1";\n';
    writeFileSync(join(dir, 'client.js'), one);
    expect(readNotice(root)?.version).toBe('2026-08-13.1');

    writeFileSync(join(dir, 'client.js'), `${one}WELCOME_NOTICE_VERSION = "2027-01-01.1";\n`);
    expect(readNotice(root)).toBeNull();
  });

  it('answers it before the page is loaded, not after', () => {
    // A write that lands after the first paint is a dialog the operator has
    // already read.
    //
    // Presence asserted before order: `indexOf` returns -1 for a call that is
    // not there at all, and -1 is less than every real index, so an
    // order-only assertion passes most loudly when the line has been deleted.
    const main = read('../electron/main.ts');
    const block = main.slice(main.indexOf("step = 'attach'"), main.indexOf('createWindow();'));
    const answered = block.indexOf('dismissDeveloperNotice()');
    const attached = block.indexOf('host.attach(window)');
    expect(answered).toBeGreaterThan(-1);
    expect(attached).toBeGreaterThan(-1);
    expect(answered).toBeLessThan(attached);
  });

  it('never fails the start over it', () => {
    // Failing the whole wiring over a courtesy would cost the workbench.
    const host = read('../electron/harness/host.ts');
    const method = host.slice(host.indexOf('async dismissDeveloperNotice'));
    const body = method.slice(0, method.indexOf('\n  /**', 1));
    expect(body).toContain('catch');
    expect(body).toContain('return false');
  });
});

/*
 * Where a conversation stands.
 *
 * The defect this closes was measured, not theorised: launched from the Finder,
 * this app's own cwd is `/`, the runtime child inherits it, and a
 * `session.create` that names no cwd falls through to `process.cwd()`
 * (`dsh-host-apiproxy`: `workspace?.path ?? payload.cwd ?? defaults.cwd`). So
 * every session on every preset stood at the root of the disk -- including the
 * authoring preset, which carries the stock shell and editor.
 */
describe('the ground a session stands on', () => {
  it('gives each task its own directory under this app, not the operator’s', async () => {
    const { taskWorkspace } = await import('../electron/harness/workspace.js');
    const dir = taskWorkspace('/Users/x/Library/Application Support/FA Foundry', 'abc123');
    expect(dir).toBe('/Users/x/Library/Application Support/FA Foundry/workspace/abc123');
  });

  it('makes it real, because a cwd that is not there refuses every path tool', async () => {
    // The runtime resolves a cwd through `realpath`, and plugins resolve every
    // tool path against the result.
    const { ensureTaskWorkspace } = await import('../electron/harness/workspace.js');
    const root = mkdtempSync(join(tmpdir(), 'fnd-ws-'));
    const dir = ensureTaskWorkspace(root, 'task-1');
    expect(existsSync(dir)).toBe(true);
    // Idempotent: a second session on the same task must not throw.
    expect(ensureTaskWorkspace(root, 'task-1')).toBe(dir);
    rmSync(root, { recursive: true, force: true });
  });

  /*
   * The window is the one directory it must not be. A window holds `inputs/` --
   * the archived books themselves -- so standing a session in it would hand the
   * model the ledger the period fence exists to keep it out of.
   */
  it('is not the window directory', async () => {
    const { taskWorkspace } = await import('../electron/harness/workspace.js');
    expect(taskWorkspace('/var/root', 'abc')).not.toContain('windows');
    expect(taskWorkspace('/var/root', 'abc')).not.toContain('inputs');
  });

  it('is named on every session the app opens', () => {
    // A preset says which tools exist; the cwd says how far the ones that take
    // a path can reach. Dropping it here reopens the whole disk silently.
    const host = read('../electron/harness/host.ts');
    expect(host).toContain("this.rpc('session.create', { agentPreset: preset, cwd })");
    const register = read('../electron/ipc/register.ts');
    expect(register).toContain('ensureTaskWorkspace(harness.userData(), task)');
  });
});

describe('a bundled companion cannot opt itself back in', () => {
  it('sets the switches last, over anything the machine already had', () => {
    // An operator who chose the Univer plugin themselves would get to decide
    // this. Ours did not choose it; they got it inside a product, so the
    // product decides. Setting it last is what makes an ambient DO_NOT_TRACK=0
    // in a developer's shell lose rather than win.
    const env = harnessEnv(
      { DO_NOT_TRACK: '0', UNIVER_TELEMETRY_ENDPOINT: 'https://example.invalid/capture' },
      {
        home: '/h',
        varRoot: '/v',
        foundryBin: '/b',
        companionEnv: { DO_NOT_TRACK: '1', UNIVER_TELEMETRY_ENDPOINT: '' },
      },
    );
    expect(env.DO_NOT_TRACK).toBe('1');
    // Empty is not absent: the bundle reads this name as an override and an
    // empty string is how it is told there is no endpoint.
    expect(env.UNIVER_TELEMETRY_ENDPOINT).toBe('');
    expect('UNIVER_TELEMETRY_ENDPOINT' in env).toBe(true);
  });

  it('reads them from the kit manifest rather than a second copy in TypeScript', () => {
    const declared = companionEnv({
      packaged: false,
      appPath: fileURLToPath(new URL('..', import.meta.url)),
      resourcesPath: '',
    });
    expect(declared.DO_NOT_TRACK).toBe('1');
    expect(declared.UNIVER_TELEMETRY_ENDPOINT).toBe('');
  });
});

describe('the receipt row upstream depends on', () => {
  /*
   * Four upstream facts hold the receipt row up, and each of them fails
   * silently: the strip simply does not draw. A pinned runtime is a dependency
   * like any other, and these read the staged tree rather than restating what
   * it said on the day this was written.
   *
   * Unconditional on purpose. The gated pattern above (`FOUNDRY_DSH_INSTALL`)
   * goes green when its variable is absent, which is the failure mode this is
   * meant to catch. When the tree is genuinely not staged there is nothing to
   * check and the assertion says so rather than passing quietly.
   */
  const dsh = fileURLToPath(new URL('../extra/dsh/node_modules/@deepseek-ai', import.meta.url));
  const staged = existsSync(dsh);
  const vendored = (rel: string) => readFileSync(join(dsh, rel), 'utf8');

  it.runIf(staged)('still lets a tool project a presentation payload', () => {
    // Our `output.presentationMeta` is the only path the receipt takes to the
    // browser. Renamed or dropped upstream, `register` would refuse the
    // definition outright -- which is loud -- but a silent relaxation of the
    // type is not, so the declaration is what gets read.
    const types = vendored('dsh-tools/lib/types/index.d.ts');
    expect(types).toContain('presentationMeta?(args: unknown, value: JsonValue): JsonValue');
    expect(types).toContain('Pure replayable presentation projection, computed only for top-level calls');
  });

  it.runIf(staged)('still calls it for top-level calls only, and fails the call if it throws', () => {
    // Both halves of why the projector must be total. If the guard or the
    // rethrow changed, ours could start throwing into a completed close.
    const tools = vendored('dsh-tools/lib/index.js');
    expect(tools).toContain('exec.parent === void 0 && tool.output.presentationMeta !== void 0');
    expect(tools).toContain('throw projectionError(tool.name, "presentationMeta", error)');
  });

  it.runIf(staged)('still lands the payload on the settled node as meta', () => {
    // `block.meta` is what the row reads. The node type is where it is
    // declared, and a rename there is exactly the silent break.
    const node = vendored('dsh-client-runtime/lib/types/client/sessions/conversation.d.ts');
    expect(node).toContain("kind: 'tool-result'");
    expect(node).toContain('meta?: unknown;');
  });

  it.runIf(staged)('still offers a keyed tool view dispatched on the wire tool name', () => {
    // The typed contract rather than the runner's serialized doc blob: the blob
    // is generated prose and reflows, the declaration is the thing a bump would
    // actually have to change.
    //
    // `keyed` matters as much as the name. A single-occupant slot takes a
    // priority where this one takes a key, so a change of kind would make our
    // registration refused rather than merely ignored.
    const slots = vendored('dsh-client-ui-tool/lib/types/client/contract/slots.d.ts');
    expect(slots).toContain("'tool.call.toolview': {");
    expect(slots).toContain("kind: 'keyed';");
    expect(slots).toContain('owner: ToolCallOwnerProps;');
    // The two props the row is built out of.
    expect(slots).toContain('toolName: string;');
    expect(slots).toContain('block: ToolCallBlock;');

    // And our three keys are still unclaimed, so registering stays additive
    // rather than shadowing a shipped row.
    const runner = vendored('dsh-cordis-client-runner/lib/client.js');
    const taken = runner.slice(runner.indexOf('key: "tool.call.toolview"'));
    const domain = taken.slice(0, taken.indexOf('replaceRisk'));
    for (const name of ['emit-brief', 'query-locked', 'record-reference']) {
      expect(domain).not.toContain(`key '${name}'`);
    }
  });

  it('says so rather than passing quietly when the runtime is not staged', () => {
    // The whole point of the four above. If this ever fails, the staged tree
    // moved and those tests have been green without reading anything.
    expect(staged || !existsSync(fileURLToPath(new URL('../extra/dsh', import.meta.url)))).toBe(true);
  });
});

describe('our own half of the receipt row', () => {
  /*
   * The upstream contract holding and our side still matching it are two
   * different claims. These read the bundle rather than importing it, because
   * `client.js` is a module-loader envelope that only runs inside the page.
   */
  const client = read('../../dsh-plugin/client.js');

  it('registers a keyed occupant for exactly the three verbs that file versions', () => {
    expect(client).toContain("ctx.slots.inject('tool.call.toolview'");
    expect(client).toContain("ctx.slots.register({ name: 'tool.call.toolview', key: toolName }, FoundryRow)");
    for (const name of ['emit-brief', 'query-locked', 'record-reference']) {
      expect(client).toContain(`'${name}':`);
    }
  });

  it('reads the payload off block.meta and never assumes it is there', () => {
    // A running call has no `meta`, and a nested one is never projected.
    expect(client).toContain('const meta = block && block.meta;');
    expect(client).toContain('Array.isArray(meta.filed) ? meta.filed : null');
  });

  it('draws the no-task case rather than drawing nothing', () => {
    // An empty receipt means the window had no timeline to file against.
    // Silence there would read as success.
    expect(client).toContain('未登记');
  });
});

describe('the profile manifest is written carefully', () => {
  /*
   * The failure this closes: an operator saw an unstyled upstream page reading
   * `failed to import loader entry (@deepseek-ai/dsh-session-log-export)`,
   * naming a bundle that was fine. `installPlugin` rewrites the profile
   * manifest on every start, and the harness home comes from `userData`, which
   * is one path for every copy of this app -- so a second launch rewrote that
   * file underneath the first one's runtime.
   */
  const scratch = () => mkdtempSync(join(tmpdir(), 'fnd-manifest-'));

  it('does not touch the file when the bytes already match', async () => {
    const { writeIfChanged } = await import('../electron/harness/wiring.js');
    const dir = scratch();
    try {
      const target = join(dir, 'package.json');
      expect(writeIfChanged(target, '{"a":1}\n')).toBe(true);
      const first = statSync(target).mtimeMs;
      // The ordinary case: every start after the first says exactly this.
      expect(writeIfChanged(target, '{"a":1}\n')).toBe(false);
      expect(statSync(target).mtimeMs).toBe(first);
      expect(writeIfChanged(target, '{"a":2}\n')).toBe(true);
      expect(readFileSync(target, 'utf8')).toBe('{"a":2}\n');
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it('leaves no temporary file behind, on success or on failure', async () => {
    const { writeIfChanged } = await import('../electron/harness/wiring.js');
    const dir = scratch();
    try {
      writeIfChanged(join(dir, 'package.json'), '{"a":1}\n');
      expect(readdirSync(dir)).toEqual(['package.json']);
      // A path that cannot be written: the temp must not survive the throw.
      expect(() => writeIfChanged(join(dir, 'nope', 'package.json'), 'x')).toThrow();
      expect(readdirSync(dir)).toEqual(['package.json']);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it('writes through a rename, so a reader never sees half a manifest', () => {
    // The property that matters is atomicity, and the way it is obtained is
    // the rename. Asserted on the source because a race cannot be provoked
    // reliably in a unit test, and a future edit that drops the rename would
    // otherwise pass everything above.
    const source = read('../electron/harness/wiring.ts');
    expect(source).toContain('renameSync(temp, target)');
    expect(source).not.toMatch(/writeFileSync\(manifestPath/);
  });
});

describe('only one instance may touch the store', () => {
  it('takes the lock before anything reads or writes, and quits if it loses', () => {
    // Read from the source: `app.requestSingleInstanceLock()` cannot be
    // exercised without a real Electron app object, and what has to stay true
    // is the ordering -- the lock is taken at module scope, above
    // `whenReady`, so the losing process never reaches `adoptFormerState` or
    // `installPlugin`.
    const source = read('../electron/main.ts');
    const lock = source.indexOf('requestSingleInstanceLock');
    const ready = source.indexOf('app.whenReady()');
    const adopt = source.indexOf('adoptFormerState();');
    expect(lock).toBeGreaterThan(-1);
    expect(lock).toBeLessThan(ready);
    expect(ready).toBeLessThan(adopt);
    expect(source).toContain('app.quit()');
    // And the winner surfaces itself rather than ignoring the second launch.
    expect(source).toContain("app.on('second-instance'");
    // `whenReady` still fires for the loser, so it checks again.
    expect(source).toContain('if (!app.hasSingleInstanceLock()) return;');
  });
});
