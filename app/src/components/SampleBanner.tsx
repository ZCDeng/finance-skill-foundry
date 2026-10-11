import { useState } from 'react';
import { Button } from './ui/button.js';
import type { TaskRow } from '../bridge.js';
import { usePreferences } from './Preferences.js';

/**
 * The line under the header of an example task, saying what it is and what was done for the reader.
 *
 * The reference task is only softly read-only: anything in it can be changed, and 重建参考结果 puts it
 * back as the example made it. What the example filled in carries 示例预置, never a manager's name.
 *
 * The note is for the first look: 知道了 folds it to the 示例 tag beside the action, for every task of that kind,
 * and the tag opens it again. A note that says something is wrong (rebuilding, unfinished, an error) never folds.
 */
export function SampleBanner({ task, building, error, onRebuild, onReference }: {
  task: TaskRow;
  /** The reference is being built or rebuilt right now. */
  building: boolean;
  error: string;
  onRebuild?(): void;
  onReference?(): void;
}) {
  const kind = task.sample;
  const { preferences, set } = usePreferences();
  const [unfolded, setUnfolded] = useState(false);
  const [readHere, setReadHere] = useState(false);
  if (!kind) return null;
  const newer = task.sample_outdated && kind !== 'legacy'
    ? <> 示例资料已有新版本，可在使用指南「第一次使用」里换成新版示例。</> : null;
  let text;
  let action = null;
  let steady = false;
  if (kind === 'reference') {
    if (building) text = <>正在按示例资料重新生成参考结果，大约需要一分钟，完成后会自动打开。</>;
    else if (task.sample_ready === false) {
      text = <>参考结果没有生成完，可能是上次生成时应用被关闭了。点「重建参考结果」重新生成。</>;
    } else {
      text = <>这是示例做好的参考结果：表结构、控制确认、差异处置和文稿都按华宸资料预先做好，标注「示例预置」，不是经理的确认。
        可以随意查看和改动，改乱了点「重建参考结果」恢复原样。{newer}</>;
      steady = true;
    }
    if (onRebuild) action = <Button size="sm" variant="outline" type="button" disabled={building} onClick={onRebuild}>
      {building ? '正在重建…' : '重建参考结果'}</Button>;
  } else if (kind === 'practice') {
    text = <>这是练习用的示例任务，资料是随包附带的华宸物业 8 月套表，所有操作只影响这个任务。按使用指南「5 分钟快速开始」一步步做；想先看做完的样子，打开参考结果。{newer}</>;
    steady = true;
    if (onReference) action = <Button size="sm" variant="outline" type="button" disabled={building} onClick={onReference}>
      {building ? '参考结果生成中…' : '打开参考结果'}</Button>;
  } else if (kind === 'next_month') {
    text = <>这是 9 月的练习任务：表格和 8 月同形状，用来体验下个月导入时表结构自动采用。{newer}</>;
    steady = true;
  } else {
    text = <>这是旧版的 6 月示例任务。新版示例换成了华宸物业 8 月资料，可在使用指南「第一次使用」里换成新版示例。</>;
  }
  const read = readHere || preferences.samples_read.includes(kind);
  if (steady && read && !unfolded && !error) {
    return <div className="workspace-sample workspace-sample--folded" role="note" aria-label="示例任务说明">
      <button type="button" className="workspace-sample__tag" aria-expanded={false} title="这是示例任务，点开看说明"
        onClick={() => setUnfolded(true)}>示例</button>
      {action}
    </div>;
  }
  const markRead = () => {
    setReadHere(true);
    setUnfolded(false);
    if (!preferences.samples_read.includes(kind)) void set({ samples_read: [...preferences.samples_read, kind] }).catch(() => {});
  };
  return <div className="workspace-sample" role="note" aria-label="示例任务说明">
    <span className="workspace-sample__tag">示例</span>
    <p>{text}</p>
    {action}
    {steady ? <Button size="sm" variant="ghost" type="button" onClick={markRead}>知道了</Button> : null}
    {error ? <p role="alert" className="workspace-sample__error">{error}</p> : null}
  </div>;
}
