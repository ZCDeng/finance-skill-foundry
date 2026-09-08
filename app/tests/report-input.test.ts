import { mkdtemp, mkdir, readFile, stat, symlink, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import * as path from 'node:path';
import { describe, it, expect } from 'vitest';
import { withDraftSpec } from '../electron/reports/input.js';
import { imageResourceReferences, localReportResources } from '../electron/reports/resources.js';

describe('large structured draft transport', () => {
  it('preserves images and Unicode outside argv and removes the private file after failure', async () => {
    let temporary = '';
    const spec = { body: '财务 123.4500\n'.repeat(8_000) };
    await expect(withDraftSpec(spec, async (args) => {
      expect(args[0]).toBe('--spec-file'); temporary = args[1];
      expect((await stat(temporary)).mode & 0o777).toBe(0o600);
      expect(JSON.parse(await readFile(temporary, 'utf8'))).toEqual(spec);
      throw new Error('save failed');
    })).rejects.toThrow('save failed');
    await expect(stat(temporary)).rejects.toMatchObject({ code: 'ENOENT' });
  });
});

describe('local document images', () => {
  it('embeds only PNG/JPEG in the selected document directory, without following an escape or network URL', async () => {
    const root = await mkdtemp(path.join(tmpdir(), 'report-image-test-'));
    try {
      const selected = path.join(root, 'selected'); await mkdir(selected);
      const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+cHtQAAAAASUVORK5CYII=', 'base64');
      await writeFile(path.join(selected, '图.png'), png);
      await writeFile(path.join(root, 'private.png'), png);
      await symlink(path.join(root, 'private.png'), path.join(selected, 'escape.png'));
      const refs = imageResourceReferences(Buffer.from('<script>fetch("secret")</script><img src="图.png"><img src="../private.png"><img src="escape.png"><img src="https://invalid.test/image.png">'), 'html');
      const resources = await localReportResources(path.join(selected, 'report.html'), refs, new AbortController().signal);
      expect(Object.keys(resources)).toEqual(['图.png']);
      expect(resources['图.png']).toBe(`data:image/png;base64,${png.toString('base64')}`);
      expect(imageResourceReferences(Buffer.from('![logo](图.png "logo")'), 'md')).toEqual(['图.png']);
    } finally { await rm(root, { recursive: true, force: true }); }
  });
  it('honors cancellation before reading assets', async () => {
    const controller = new AbortController(); controller.abort();
    await expect(localReportResources(path.join(tmpdir(), 'report.md'), ['a.png'], controller.signal)).rejects.toThrow('已取消');
  });
});
