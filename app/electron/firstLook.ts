import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import * as path from 'node:path';

/**
 * 60 秒看看它能做什么: the first look 总览 offers once, over the sample's 参考结果 board. Once the manager has seen it
 * through or closed it, it is not offered again. One flag in a file in this app's own folder, beside the appearance.
 */
const FILE = 'first-look.json';

/** Whether it was seen through or closed. Missing or unreadable is not yet. */
export function readFirstLook(folder: string): boolean {
  try {
    return (JSON.parse(readFileSync(path.join(folder, FILE), 'utf8')) as { done?: unknown }).done === true;
  } catch {
    return false;
  }
}

/** Written beside and renamed over, so a crash mid-write leaves the old file and not half a file. */
export function writeFirstLook(folder: string): void {
  mkdirSync(folder, { recursive: true });
  const target = path.join(folder, FILE);
  const pending = `${target}.${process.pid}.tmp`;
  writeFileSync(pending, `${JSON.stringify({ done: true })}\n`);
  renameSync(pending, target);
}
