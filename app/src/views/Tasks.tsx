import { FileClock, Layers } from 'lucide-react';

import { type TaskRow, when } from '../bridge.js';

/**
 * Every task, oldest first, the way the store lists them.
 *
 * A period's title and its window count are the two things that tell an operator
 * which row is theirs: a task with two windows had a re-import, and that is the
 * one whose old brief still has follow-ups hanging off it.
 */
export function Tasks({ tasks, onOpen }: { tasks: TaskRow[]; onOpen(id: string): void }) {
  if (tasks.length === 0) {
    return <p className="fnd-empty">还没有任务。用 foundry task-new 建一个, 或者从一次导入开始, 第一个碰到它的任务会把窗口收编。</p>;
  }
  return (
    <div className="fnd-stack">
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
