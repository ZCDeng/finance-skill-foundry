import { useCallback, useEffect, useState } from 'react';

import './styles/base.css';

import { Shell } from './components/Shell.js';
import { type Answer, type DeliverableRow, type TaskDetail as Detail, type TaskRow, bridge } from './bridge.js';
import { Deliverables } from './views/Deliverables.js';
import { TaskDetail } from './views/TaskDetail.js';
import { Tasks } from './views/Tasks.js';

type Screen = 'tasks' | 'deliverables';

/** A refusal is a sentence the store wrote. Show it, do not translate it. */
function Refusal({ message }: { message: string }) {
  return <p className="fnd-refusal">{message}</p>;
}

export function App() {
  const api = bridge();
  const [screen, setScreen] = useState<Screen>('tasks');
  const [open, setOpen] = useState<string | null>(null);
  const [tasks, setTasks] = useState<TaskRow[]>([]);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [gallery, setGallery] = useState<{ task: TaskRow; row: DeliverableRow }[]>([]);
  const [reading, setReading] = useState<{ sha: string; text: string } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  /** Every answer lands here, so one refusal path serves every screen. */
  const take = useCallback(<T,>(answer: Answer<T>, use: (value: T) => void) => {
    if (answer.ok) {
      setProblem(null);
      use(answer.value);
    } else {
      setProblem(answer.message);
    }
  }, []);

  useEffect(() => {
    if (!api) return;
    if (screen === 'tasks' && open === null) void api.tasks().then((a) => take(a, setTasks));
    if (screen === 'deliverables') void api.gallery().then((a) => take(a, setGallery));
  }, [api, screen, open, take]);

  useEffect(() => {
    if (!api || open === null) {
      setDetail(null);
      return;
    }
    setReading(null);
    void api.task(open).then((a) => take(a, setDetail));
  }, [api, open, take]);

  const read = useCallback(
    (sha: string) => {
      if (!api || open === null) return;
      void api.deliverableText(open, sha).then((a) => take(a, (text) => setReading({ sha, text })));
    },
    [api, open, take],
  );

  if (!api) {
    return (
      <Shell screen={screen} onScreen={setScreen}>
        <p className="fnd-empty">
          这个窗口没有接到 foundry。它在 Electron 之外跑起来时就是这样, 主进程还没起来。
        </p>
      </Shell>
    );
  }

  return (
    <Shell screen={screen} onScreen={(next) => { setOpen(null); setScreen(next); }}>
      {problem ? <Refusal message={problem} /> : null}
      {screen === 'tasks' && open === null ? <Tasks tasks={tasks} onOpen={setOpen} /> : null}
      {screen === 'tasks' && open !== null && detail ? (
        <TaskDetail detail={detail} onBack={() => setOpen(null)} onRead={read} reading={reading} />
      ) : null}
      {screen === 'deliverables' ? <Deliverables rows={gallery} /> : null}
    </Shell>
  );
}
