// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { Chip, Marks } from '../src/components/Chip.js';
import { WiringTrouble } from '../src/views/Workbench.js';
import { Deliverables } from '../src/views/Deliverables.js';
import { Tasks } from '../src/views/Tasks.js';
import type { DeliverableRow, TaskRow } from '../src/bridge.js';

afterEach(cleanup);

const TASK: TaskRow = {
  id: 'a'.repeat(32),
  title: '2026-08 月度经营分析',
  period: '2026-08',
  skill_id: null,
  created_at: '2026-08-30T02:00:00Z',
  windows: 2,
};

const ROW: DeliverableRow = {
  seq: 3,
  kind: 'workpaper',
  window_id: 'b'.repeat(32),
  sha256: 'c'.repeat(64),
  bytes: 8421,
  cause: 'query-locked:followup-1',
  session_id: 'sess-leader',
  at: '2026-08-30T06:22:07Z',
};

describe('the task list', () => {
  const noop = () => {};

  it('says how many windows a task owns', () => {
    // Two windows means a re-import happened, and that is the task whose older
    // brief still has follow-ups hanging off it.
    render(<Tasks tasks={[TASK]} busy={false} onOpen={noop} onCreate={noop} />);
    expect(screen.getByText('2026-08 月度经营分析')).toBeTruthy();
    expect(screen.getByText(/2 个窗口/)).toBeTruthy();
  });

  /*
   * The empty state used to read "用 foundry task-new 建一个". That CLI lives
   * inside the application bundle and is on nobody's PATH, so on a machine that
   * had only installed the app it was an instruction that could not be carried
   * out -- and with no task there is no session, and with no session the harness
   * view never gets a rectangle. The whole window was unusable from a cold
   * install. What the empty state must have is a control, not a sentence.
   */
  it('offers a way to make the first task, on a store with none', () => {
    render(<Tasks tasks={[]} busy={false} onOpen={noop} onCreate={noop} />);
    expect(screen.getByLabelText('任务名')).toBeTruthy();
    expect(screen.getByRole('button', { name: /新建任务/ })).toBeTruthy();
    expect(screen.queryByText(/task-new/)).toBeNull();
  });

  it('hands up the title and the period an operator typed', () => {
    const made: [string, string][] = [];
    render(
      <Tasks tasks={[]} busy={false} onOpen={noop} onCreate={(t, p) => made.push([t, p])} />,
    );
    fireEvent.change(screen.getByLabelText('任务名'), { target: { value: '  华东区 8 月回款  ' } });
    fireEvent.change(screen.getByLabelText('期间'), { target: { value: '2026-08' } });
    fireEvent.click(screen.getByRole('button', { name: /新建任务/ }));
    expect(made).toEqual([['华东区 8 月回款', '2026-08']]);
  });

  it('will not create a task with no title', () => {
    const made: string[] = [];
    render(<Tasks tasks={[]} busy={false} onOpen={noop} onCreate={(t) => made.push(t)} />);
    // Whitespace is not a name. A store full of tasks called " " is a list an
    // operator cannot read, and the title is the only thing telling two apart.
    fireEvent.change(screen.getByLabelText('任务名'), { target: { value: '   ' } });
    fireEvent.click(screen.getByRole('button', { name: /新建任务/ }));
    expect(made).toEqual([]);
  });

  it('does not fire twice while a create is still in flight', () => {
    const made: string[] = [];
    render(<Tasks tasks={[]} busy onOpen={noop} onCreate={(t) => made.push(t)} />);
    fireEvent.change(screen.getByLabelText('任务名'), { target: { value: '八月' } });
    fireEvent.click(screen.getByRole('button', { name: /新建任务/ }));
    expect(made).toEqual([]);
  });
});

describe('the deliverable gallery', () => {
  it('shows the cause, which is the column that earns the screen', () => {
    // A file name says a document changed. `query-locked:followup-1` says which
    // question changed it.
    render(<Deliverables rows={[{ task: TASK, row: ROW }]} />);
    expect(screen.getByText('query-locked:followup-1')).toBeTruthy();
    expect(screen.getByText('底稿')).toBeTruthy();
    expect(screen.getByText('8.2 KB')).toBeTruthy();
    expect(screen.getByText('cccccccccccc')).toBeTruthy();
  });

  it('names a version with no conversation behind it', () => {
    render(<Deliverables rows={[{ task: TASK, row: { ...ROW, session_id: null } }]} />);
    expect(screen.getByText('无会话')).toBeTruthy();
  });
});

describe('the five words', () => {
  it('draws only the two that are not about arithmetic in colour', () => {
    const { container } = render(
      <>
        <Chip mark="claimed" />
        <Chip mark="recomputed" />
        <Chip mark="agreed" />
        <Chip mark="outside" />
        <Chip mark="absent" />
      </>,
    );
    const coloured = [...container.querySelectorAll('[data-coloured="yes"]')].map(
      (node) => node.getAttribute('data-mark'),
    );
    expect(coloured.sort()).toEqual(['absent', 'outside']);
    expect(container.querySelectorAll('.fnd-chip')).toHaveLength(5);
  });

  it('draws both halves of a follow-up tag', () => {
    const { container } = render(<Marks tag="稿外追问 / 我重算" />);
    expect(container.querySelectorAll('.fnd-chip')).toHaveLength(2);
    expect(screen.getByText('稿外追问')).toBeTruthy();
    expect(screen.getByText('我重算')).toBeTruthy();
  });

  it('draws nothing for prose', () => {
    const { container } = render(<Marks tag="本期收入合计" />);
    expect(container.querySelectorAll('.fnd-chip')).toHaveLength(0);
  });
});

describe('the data screen', () => {
  it('does not read like a task is required', async () => {
    // `launch-formulator` takes the current window, so this screen works with no
    // task open. A flat "没有任务" would read like a blocker in front of a button
    // that is about to work.
    const { DataBar } = await import('../src/views/Formulator.js');
    render(<DataBar task={null} detail={null} running={null} busy={false} onLaunch={() => {}} onStop={() => {}} />);
    expect(screen.queryByText('没有任务')).toBeNull();
    expect(screen.getByText(/租约跟着 current 走/)).toBeTruthy();
  });

  it('shows the kit’s own words when it could not confirm the process', async () => {
    // The kit launches anyway with no `ps` rather than becoming unstartable, and
    // says so on the record. This is where that reaches an operator.
    const { DataBar } = await import('../src/views/Formulator.js');
    render(
      <DataBar
        task={null}
        detail={null}
        running={{ url: 'http://127.0.0.1:5567', home: '/h', identity: 'unconfirmed: ps is not installed on this host' }}
        busy={false}
        onLaunch={() => {}}
        onStop={() => {}}
      />,
    );
    expect(screen.getByText(/unconfirmed: ps is not installed/)).toBeTruthy();
    expect(screen.getByText('http://127.0.0.1:5567')).toBeTruthy();
  });
});

describe('a half-wired workbench', () => {
  it('says nothing while the wiring is still running', () => {
    // It runs after the window is already up, so a pending state is the normal
    // first answer and must not draw an alarm.
    const { container } = render(<WiringTrouble status={{ wiring: { state: 'pending' }, consequence: null, origin: null }} />);
    expect(container.querySelector('.fnd-refusal')).toBeNull();
    expect(render(<WiringTrouble status={null} />).container.textContent).toBe('');
  });

  it('says nothing once it worked', () => {
    const { container } = render(
      <WiringTrouble status={{ wiring: { state: 'ready' }, consequence: null, origin: 'http://127.0.0.1:1' }} />,
    );
    expect(container.querySelector('.fnd-refusal')).toBeNull();
  });

  it('names what is missing and which file, when it did not', () => {
    // The harness reports its own troubles in its own page, and they are the
    // wrong troubles: a bundle that never installed surfaces as its settings
    // dialog failing to save an acknowledgement.
    render(
      <WiringTrouble
        status={{
          wiring: {
            state: 'failed',
            step: 'plugin',
            message: "Cannot find package 'finance-skill-foundry-dsh'",
          },
          consequence: '期间工具没有装进 harness。',
          origin: null,
        }}
      />,
    );
    expect(screen.getByText('工作台没有装好')).toBeTruthy();
    expect(screen.getByText('期间工具没有装进 harness。')).toBeTruthy();
    expect(screen.getByText(/Cannot find package/)).toBeTruthy();
  });
});
