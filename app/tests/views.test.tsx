// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { Chip, Marks } from '../src/components/Chip.js';
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
  it('says how many windows a task owns', () => {
    // Two windows means a re-import happened, and that is the task whose older
    // brief still has follow-ups hanging off it.
    render(<Tasks tasks={[TASK]} onOpen={() => {}} />);
    expect(screen.getByText('2026-08 月度经营分析')).toBeTruthy();
    expect(screen.getByText(/2 个窗口/)).toBeTruthy();
  });

  it('says what to do when there is nothing yet, rather than showing a blank', () => {
    render(<Tasks tasks={[]} onOpen={() => {}} />);
    expect(screen.getByText(/task-new/)).toBeTruthy();
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
