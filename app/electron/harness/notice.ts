import { readFileSync } from 'node:fs';
import { join } from 'node:path';

/**
 * The runtime's developer-preview dialog, and this app's answer to it.
 *
 * Upstream shows a modal on first load: Harness 0.1 is in testing, feedback
 * welcome, come and join the DSH plugin ecosystem. It is addressed to Harness
 * developers, and the person opening this workbench is a finance manager who did
 * not choose the runtime, cannot act on the invitation, and has a period to
 * close. The app pins the runtime and vouches for it; taking that notice on its
 * behalf is part of vouching.
 *
 * The acknowledgement goes through the runtime's own settings service rather
 * than into its `settings.yaml` by hand, and before the page is loaded rather
 * than after -- a write that lands after the first paint is a dialog the
 * operator has already seen.
 *
 * Read from the shipped bundle rather than restated here, so a pinned runtime
 * carrying a *different* notice writes that one's version. A parse that fails
 * suppresses nothing: the fallback is the dialog, which is visible and harmless,
 * and never a wrong value written into somebody's settings.
 */

export interface Notice {
  namespace: string;
  field: string;
  version: string;
}

/** The one file that defines all three constants, relative to the staged runtime. */
const CLIENT = join(
  'node_modules',
  '@deepseek-ai',
  'dsh-client-ui-settings-models',
  'lib',
  'client.js',
);

/** Each constant is defined exactly once; anything else is a bundle we do not recognise. */
function only(source: string, name: string): string | null {
  const found = [...source.matchAll(new RegExp(`${name} = "([^"]*)"`, 'g'))];
  return found.length === 1 ? found[0][1] : null;
}

export function readNotice(harnessRoot: string): Notice | null {
  let source: string;
  try {
    source = readFileSync(join(harnessRoot, CLIENT), 'utf8');
  } catch {
    return null;
  }
  const namespace = only(source, 'SETTINGS_NAMESPACE');
  const field = only(source, 'WELCOME_NOTICE_ACK_FIELD');
  const version = only(source, 'WELCOME_NOTICE_VERSION');
  if (!namespace || !field || !version) return null;
  return { namespace, field, version };
}

/** The `settings.update` payload that answers it. */
export function noticePatch(notice: Notice): Record<string, unknown> {
  return { ns: notice.namespace, patch: { [notice.field]: notice.version } };
}
