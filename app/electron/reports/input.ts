import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import * as path from 'node:path';

/** Transport only: private temporary input keeps images out of bounded OS argv. */
export async function withDraftSpec<T>(spec: unknown, invoke: (args: string[]) => Promise<T>): Promise<T> {
  if (!spec || typeof spec !== 'object' || Array.isArray(spec)) throw new Error('expected a draft object');
  const encoded = JSON.stringify(spec);
  if (Buffer.byteLength(encoded) > 32 * 1024 * 1024) throw new Error('文稿超过容量，请拆分图片或章节。');
  if (Buffer.byteLength(encoded) < 48_000) return invoke(['--spec', encoded]);
  const directory = await mkdtemp(path.join(tmpdir(), 'fa-draft-'));
  try {
    const input = path.join(directory, 'draft.json');
    await writeFile(input, encoded, { mode: 0o600 });
    return await invoke(['--spec-file', input]);
  } finally { await rm(directory, { recursive: true, force: true }); }
}
