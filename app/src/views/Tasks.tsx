import { useState } from 'react';
import { FileClock, FolderPlus, Layers } from 'lucide-react';

import { type TaskRow, when } from '../bridge.js';
import { Button } from '../components/ui/button.js';
import { Input } from '../components/ui/input.js';
import { Empty, EmptyDescription } from '../components/ui/empty.js';

/**
 * Where the first task comes from.
 *
 * This used to be a sentence telling the operator to run `foundry task-new`.
 * The CLI it named is inside the application bundle and not on anyone's PATH,
 * so on a machine that had only ever installed the app it was an instruction
 * that could not be followed -- and with no task there is no session, and with
 * no session the harness view is never given a rectangle. The window was a
 * read-only view of a store nothing could seed.
 *
 * A period is optional because a task can be named before its month is decided,
 * and the store keeps it null. The title is not: it is the only thing that tells
 * two periods apart in a list.
 */
function NewTask({ busy, onCreate }: { busy: boolean; onCreate(title: string, period: string): void }) {
  const [title, setTitle] = useState('');
  const [period, setPeriod] = useState('');
  const ready = title.trim().length > 0 && !busy;
  return (
    <form
      className="fnd-new"
      onSubmit={(event) => {
        event.preventDefault();
        if (!ready) return;
        onCreate(title.trim(), period.trim());
        setTitle('');
        setPeriod('');
      }}
    >
      <Input
        className="min-w-0 flex-1"
        value={title}
        maxLength={120}
        placeholder="任务名, 比如 华东区 8 月回款"
        aria-label="任务名"
        onChange={(event) => setTitle(event.target.value)}
       />
      <Input
        className="fnd-field--short"
        value={period}
        maxLength={32}
        placeholder="期间 2026-08"
        aria-label="期间"
        onChange={(event) => setPeriod(event.target.value)}
       />
      <Button type="submit" disabled={!ready}>
        <FolderPlus size={14} strokeWidth={1.5} aria-hidden />
        新建任务
      </Button>
    </form>
  );
}

/**
 * Every task, oldest first, the way the store lists them.
 *
 * A period's title and its window count are the two things that tell an operator
 * which row is theirs: a task with two windows had a re-import, and that is the
 * one whose old brief still has follow-ups hanging off it.
 */
export function Tasks({
  tasks,
  busy,
  onOpen,
  onCreate,
}: {
  tasks: TaskRow[];
  busy: boolean;
  onOpen(id: string): void;
  onCreate(title: string, period: string): void;
}) {
  return (
    <div className="fnd-stack">
      <NewTask busy={busy} onCreate={onCreate} />
      {tasks.length === 0 ? (
        <Empty>
          <EmptyDescription>还没有任务。上面开一个, 会话才有地方写。也可以从一次导入开始, 第一个碰到它的任务会把窗口收编。</EmptyDescription>
        </Empty>
      ) : null}
      {tasks.map((task) => (
        <button key={task.id} type="button" className="fnd-card" onClick={() => onOpen(task.id)}>
          <span className="fnd-row">
            <span className="fnd-title">{task.title}</span>
            {task.period ? <span className="fnd-muted">{task.period}</span> : null}
          </span>
          <span className="fnd-row" style={{ marginTop: 8 }}>
            <span className="fnd-muted">
              <Layers size={13} strokeWidth={1.5} aria-hidden />
              {` ${task.windows} 个窗口`}
            </span>
            <span className="fnd-muted">
              <FileClock size={13} strokeWidth={1.5} aria-hidden />
              {` ${when(task.created_at)}`}
            </span>
          </span>
        </button>
      ))}
    </div>
  );
}
