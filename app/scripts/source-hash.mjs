/**
 * A fingerprint of the `foundry` package a freeze embeds, plus the script that froze it.
 *
 * Both frozen bundles carry `foundry`: the CLI as its whole program, Formulator
 * so its locked-catalog connector can import. Neither ever looks at the checkout
 * again, so a bundle can be arbitrarily older than the source it was made from.
 * Each build stamps this and each `--check` recomputes it.
 *
 * Path and content, both: a renamed file with identical bytes is a different
 * tree, and `install_presets` walks directories by name.
 */

import { createHash } from 'node:crypto';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { basename, join, relative } from 'node:path';

export function foundrySourceHash(kit, script) {
  const root = join(kit, 'foundry');
  const hash = createHash('sha256');
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true }).sort((a, b) =>
      a.name < b.name ? -1 : 1,
    )) {
      if (entry.name === '__pycache__' || entry.name.endsWith('.pyc')) continue;
      const path = join(dir, entry.name);
      if (entry.isDirectory()) walk(path);
      else {
        hash.update(relative(root, path).split('/').join('/'));
        hash.update(readFileSync(path));
      }
    }
  };
  walk(root);
  hash.update(basename(script));
  hash.update(readFileSync(script));
  return hash.digest('hex');
}

/** The fingerprint a stamp recorded, or null when it predates them. */
export function stampedHash(stamp) {
  if (!existsSync(stamp)) return null;
  const line = readFileSync(stamp, 'utf8')
    .split('\n')
    .find((row) => row.startsWith('source: '));
  return line ? line.slice(8).trim() : null;
}
