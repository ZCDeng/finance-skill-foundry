// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';

import { afterEach, describe, expect, it, vi } from 'vitest';

import { Chip, Marks } from '../src/components/Chip.js';
import { Reader } from '../src/components/Reader.js';
import { WiringTrouble } from '../src/views/Workbench.js';
import { Deliverables } from '../src/views/Deliverables.js';
import { Tasks } from '../src/views/Tasks.js';
import { TaskDetail } from '../src/views/TaskDetail.js';
import { Analysis } from '../src/views/Analysis.js';
import { type Answer, type AnalysisDraft, type AnalysisState, type Bridge, type DeliverableRow, type TaskRow, isWorkbook } from '../src/bridge.js';

afterEach(() => { cleanup(); delete (globalThis as unknown as { foundry?: Partial<Bridge> }).foundry; vi.clearAllMocks(); });

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


const success = <T,>(value: T): Answer<T> => ({ ok: true, value });
function installEditorGeometryPolyfill() {
  Element.prototype.getClientRects = vi.fn(() => ({ length: 1, item: () => null, [0]: new DOMRect(0, 0, 120, 24) } as unknown as DOMRectList));
  Element.prototype.getBoundingClientRect = vi.fn(() => new DOMRect(0, 0, 120, 24));
  Range.prototype.getClientRects = vi.fn(() => ({ length: 1, item: () => null, [0]: new DOMRect(0, 0, 120, 24) } as unknown as DOMRectList));
  Range.prototype.getBoundingClientRect = vi.fn(() => new DOMRect(0, 0, 120, 24));
  window.scrollBy = vi.fn();
}

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

/** The gallery's own props, for the cases that only look at the list. */
const GALLERY = {
  open: null,
  onOpen: () => {},
  onOpenWorkbook: () => {},
  onExport: () => {},
  busy: null,
  onBack: () => {},
};

describe('the deliverable gallery', () => {
  it('shows the cause, which is the column that earns the screen', () => {
    // A file name says a document changed. `query-locked:followup-1` says which
    // question changed it.
    render(<Deliverables rows={[{ task: TASK, row: ROW }]} {...GALLERY} />);
    expect(screen.getByText('query-locked:followup-1')).toBeTruthy();
    expect(screen.getByText('底稿')).toBeTruthy();
    expect(screen.getByRole('columnheader', { name: '期间' })).toBeTruthy();
    // Size, digest and session place a version for an audit, not for choosing one.
    expect(screen.queryByText('8.2 KB')).toBeNull();
    expect(screen.queryByText('cccccccccccc')).toBeNull();
    expect(screen.queryByRole('columnheader', { name: '会话' })).toBeNull();
  });

  it('keeps session, size and digest under the opened version\'s technical details, naming a missing session', () => {
    render(<Deliverables rows={[]} {...GALLERY} open={{ task: TASK, row: { ...ROW, session_id: null }, text: '正文' }} />);
    const technical = screen.getByText('技术信息').closest('details')!;
    expect(technical.open).toBe(false);
    expect(within(technical).getByText('无会话')).toBeTruthy();
    expect(within(technical).getByText('8.2 KB')).toBeTruthy();
    expect(within(technical).getByText('cccccccccccc')).toBeTruthy();
  });
});

describe('the six words', () => {
  it('draws only the three that are not this window\'s arithmetic in colour', () => {
    const { container } = render(
      <>
        <Chip mark="claimed" />
        <Chip mark="recomputed" />
        <Chip mark="agreed" />
        <Chip mark="outside" />
        <Chip mark="absent" />
        <Chip mark="external" />
      </>,
    );
    const coloured = [...container.querySelectorAll('[data-coloured="yes"]')].map(
      (node) => node.getAttribute('data-mark'),
    );
    expect(coloured.sort()).toEqual(['absent', 'external', 'outside']);
    expect(container.querySelectorAll('.fnd-chip')).toHaveLength(6);
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

describe('the shell', () => {
  it('says the product name, once, in the header', async () => {
    const { Shell } = await import('../src/components/Shell.js');
    render(
      <Shell screen="workbench" onScreen={() => {}}>
        <p>x</p>
      </Shell>,
    );
    expect(screen.getByText('FA Foundry')).toBeTruthy();
  });

  /*
   * The order is the product's answer to "what is this". Opening on 任务 put a
   * form for naming a period in front of the runtime that explains why anyone
   * would name one.
   */
  it('keeps analysis and conversation in one destination while retaining the archive', async () => {
    const { Shell } = await import('../src/components/Shell.js');
    const { container } = render(
      <Shell screen="workbench" onScreen={() => {}}>
        <p>x</p>
      </Shell>,
    );
    const tabs = [...container.querySelectorAll('.fnd-head__tab')].map((n) => n.textContent);
    expect(tabs).toEqual(['工作区', '成果库']);
    expect(container.querySelector('.fnd-head__tab[aria-current="page"]')?.textContent).toBe('工作区');
    expect(screen.queryByRole('button', { name: '对话' })).toBeNull();
  });

  /*
   * An icon with no visible text, so the accessible name is the only name it
   * has. Dropping the label and the `aria-label` together would leave a
   * control announced as "button".
   */
  it('keeps a name on the help control after it lost its label', async () => {
    const { Shell } = await import('../src/components/Shell.js');
    render(
      <Shell screen="workbench" onScreen={() => {}} onGuide={() => {}}>
        <p>x</p>
      </Shell>,
    );
    const help = screen.getByRole('button', { name: '怎么用' });
    expect(help.textContent).toBe('');
  });

  it('offers the guide back only where it can be drawn', async () => {
    const { Shell } = await import('../src/components/Shell.js');
    const { container, rerender } = render(
      <Shell screen="workbench" onScreen={() => {}} onGuide={() => {}}>
        <p>x</p>
      </Shell>,
    );
    expect(container.querySelector('.fnd-head__help')).toBeTruthy();
    rerender(
      <Shell screen="tasks" onScreen={() => {}}>
        <p>x</p>
      </Shell>,
    );
    expect(container.querySelector('.fnd-head__help')).toBeNull();
  });

  /*
   * R14, KTD13. The gold title-bar rules in components.css are written as
   * `.fnd-head .fnd-head__tab…`. This is the DOM those selectors have to hit,
   * and the reused back and Formulator buttons they have to miss.
   */
  it('lets the gold title-bar selectors reach the two tabs and none of the reused ones', async () => {
    const { Shell } = await import('../src/components/Shell.js');
    const { DataBar } = await import('../src/views/Formulator.js');
    const { container } = render(
      <Shell
        screen="deliverables"
        onScreen={() => {}}
        strip={<DataBar task={null} detail={null} running={null} busy={false} onLaunch={() => {}} onStop={() => {}} />}
      >
        <Deliverables
          rows={[{ task: TASK, row: ROW }]}
          open={{ task: TASK, row: ROW, text: null }}
          onOpen={() => {}}
          onOpenWorkbook={() => {}}
          onExport={() => {}}
          busy={null}
          onBack={() => {}}
        />
      </Shell>,
    );
    const scoped = [...container.querySelectorAll('.fnd-head .fnd-head__tab')].map((n) => n.textContent);
    expect(scoped).toEqual(['工作区', '成果库']);
    const current = [...container.querySelectorAll(".fnd-head .fnd-head__tab[aria-current='page']")];
    expect(current.map((n) => n.textContent)).toEqual(['成果库']);
    const reused = [...container.querySelectorAll('.fnd-head__tab')].filter((n) => !n.closest('.fnd-head'));
    expect(reused.map((n) => n.textContent?.trim())).toEqual(expect.arrayContaining(['起 Data Formulator', '交付物']));
    for (const node of reused) expect(node.hasAttribute('aria-current')).toBe(false);
  });

  /*
   * The help control is the shadcn ghost Button. Its colour utilities sit in a
   * later cascade layer than components.css, so its title-bar colours are the
   * classes it renders with, and they are read here.
   */
  it('keeps the help control neutral at rest and gold only on hover', async () => {
    const { Shell } = await import('../src/components/Shell.js');
    render(
      <Shell screen="workbench" onScreen={() => {}} onGuide={() => {}}>
        <p>x</p>
      </Shell>,
    );
    const classes = screen.getByRole('button', { name: '怎么用' }).className.split(/\s+/);
    expect(classes).toEqual(
      expect.arrayContaining([
        'text-[var(--fnd-muted)]',
        'bg-transparent',
        'enabled:hover:text-[var(--fnd-selected)]',
        'enabled:hover:bg-transparent',
      ]),
    );
    expect(classes).not.toContain('enabled:hover:text-foreground');
    expect(classes).not.toContain('enabled:hover:bg-[var(--fnd-surface-strong)]');
    // Keyboard focus keeps the state it is in and adds the separate ring from
    // `.fnd-head__help:focus-visible`; no focus class repaints the icon.
    expect(classes.filter((name) => /(^|:)focus(-visible)?:.*(text|bg)-/.test(name))).toEqual([]);
  });
});


describe('the analysis report page', () => {
  it('keeps print preview as a real third mode between edit and read', async () => {
    installEditorGeometryPolyfill();
    const draft: AnalysisDraft = {
      task_id: TASK.id,
      schema_version: 1,
      created_at: TASK.created_at,
      id: 'f'.repeat(32),
      title: '经营简报',
      body: '# 管理摘要\n利润改善。\n',
      run_ids: [],
      claims: [],
      publication_status: 'archived',
      review_status: 'accepted',
      limitations: [],
    };
    const state: AnalysisState = { task_id: TASK.id, datasets: [], analyses: [], runs: [], drafts: [draft], methods: [] };
    const reportPreview = vi.fn(async () => success({ html: '<html><body><main>正式预览内容</main></body></html>' }));
    (globalThis as unknown as { foundry: Partial<Bridge> }).foundry = {
      analysisState: vi.fn(async () => success(state)),
      reportPreview,
    };

    render(<Analysis task={TASK} tasks={[TASK]} embedded section="drafts" onPick={() => {}} onNew={() => {}} onChat={() => {}} />);

    expect(await screen.findByRole('article', { name: '文稿阅读' })).toBeTruthy();
    fireEvent.click(screen.getByRole('tab', { name: '打印预览' }));
    await waitFor(() => expect(reportPreview).toHaveBeenCalledWith(TASK.id, expect.objectContaining({ content: expect.any(Array) }), '经营简报'));
    expect(screen.getByTitle('正式预览')).toBeTruthy();

    fireEvent.click(screen.getByRole('tab', { name: /^编辑$/ }));
    expect(screen.getByLabelText('可视化文稿编辑器')).toBeTruthy();

    fireEvent.click(screen.getByRole('tab', { name: /^阅读$/ }));
    expect(screen.getByRole('article', { name: '文稿阅读' }).textContent).toContain('利润改善。');
  });
});

describe('the task bar', () => {
  const noop = () => {};
  const bar = async () => (await import('../src/views/Workbench.js')).TaskBar;

  it('offers direct analysis and keeps legacy workflows in a selector', async () => {
    // They used to be cards on a panel the harness view covered, reachable only
    // after a task had been made on another screen and opened on a third.
    const TaskBar = await bar();
    render(
      <TaskBar
        tasks={[TASK]}
        task={TASK}
        detail={null}
        session={null}
        busy={false}
        onPick={noop}
        onNew={noop}
        onOpen={noop}
      />,
    );
    for (const label of ['写方法', '开始本期', '追问']) {
      expect(screen.getByRole('option', { name: label })).toBeTruthy();
    }
  });

  it('will not open a session with nothing to bind it to', async () => {
    const TaskBar = await bar();
    render(
      <TaskBar
        tasks={[]}
        task={null}
        detail={null}
        session={null}
        busy={false}
        onPick={noop}
        onNew={noop}
        onOpen={noop}
      />,
    );
    expect(screen.getByRole('button', { name: /继续分析/ }).hasAttribute('disabled')).toBe(true);
    expect(screen.getByText('还没有选任务')).toBeTruthy();
  });

  /*
   * The page below is upstream's, and a conversation started inside it runs on
   * whatever preset that page defaults to. The period tools it can still reach
   * resolve their task from the current window rather than from the row this
   * strip names, and an operator has no other way to learn that.
   */
  it('says so when the conversation did not come through these buttons', async () => {
    const TaskBar = await bar();
    render(
      <TaskBar
        tasks={[TASK]}
        task={TASK}
        detail={null}
        session={null}
        busy={false}
        onPick={noop}
        onNew={noop}
        onOpen={noop}
      />,
    );
    expect(screen.getByText(/选择任务后继续分析/)).toBeTruthy();
  });

  it('names the role, the round and the preset once one did', async () => {
    const TaskBar = await bar();
    render(
      <TaskBar
        tasks={[TASK]}
        task={TASK}
        detail={{
          task: { ...TASK },
          windows: [],
          sessions: [{ session_id: 's1', role: 'period', opened_at: '2026-08-30T02:00:00Z' }],
          deliverables: [],
        }}
        session={{ sessionId: 's1', preset: 'period', intent: 'period' }}
        busy={false}
        onPick={noop}
        onNew={noop}
        onOpen={noop}
      />,
    );
    expect(screen.getByText(/期间 · 第 1 轮/)).toBeTruthy();
  });

  it('switches the binding, and asks for a new task through the same control', async () => {
    const TaskBar = await bar();
    const picked: string[] = [];
    let asked = 0;
    const other: TaskRow = { ...TASK, id: 'd'.repeat(32), title: '九月' };
    render(
      <TaskBar
        tasks={[TASK, other]}
        task={TASK}
        detail={null}
        session={null}
        busy={false}
        onPick={(id) => picked.push(id)}
        onNew={() => {
          asked += 1;
        }}
        onOpen={noop}
      />,
    );
    const picker = screen.getByLabelText('任务');
    fireEvent.change(picker, { target: { value: other.id } });
    expect(picked).toEqual([other.id]);
    fireEvent.change(picker, { target: { value: '__new__' } });
    expect(asked).toBe(1);
  });
});

describe('the guide', () => {
  const guide = async () => (await import('../src/views/Guide.js')).Guide;

  /*
   * The one press that gets a cold install moving. Before this, starting meant
   * naming a task on one screen, finding it on another, and choosing a way in
   * on a third -- with nothing on any of them saying that was the sequence.
   */
  it('names a task and starts a period in one press', async () => {
    const Guide = await guide();
    const started: [string, string][] = [];
    render(<Guide busy={false} canStart onStart={(t, p) => started.push([t, p])} onDismiss={() => {}} />);
    fireEvent.change(screen.getByLabelText('任务名'), { target: { value: '  华东区 8 月回款 ' } });
    fireEvent.change(screen.getByLabelText('期间'), { target: { value: '2026-08' } });
    fireEvent.click(screen.getByRole('button', { name: /建任务并开始本期/ }));
    expect(started).toEqual([['华东区 8 月回款', '2026-08']]);
  });

  it('will not start on a title that is only whitespace', async () => {
    const Guide = await guide();
    const started: string[] = [];
    render(<Guide busy={false} canStart onStart={(t) => started.push(t)} onDismiss={() => {}} />);
    fireEvent.change(screen.getByLabelText('任务名'), { target: { value: '   ' } });
    fireEvent.click(screen.getByRole('button', { name: /建任务并开始本期/ }));
    expect(started).toEqual([]);
  });

  it('does not offer a start a build with no harness cannot honour', async () => {
    const Guide = await guide();
    render(<Guide busy={false} canStart={false} onStart={() => {}} onDismiss={() => {}} />);
    fireEvent.change(screen.getByLabelText('任务名'), { target: { value: '八月' } });
    expect(screen.getByRole('button', { name: /建任务并开始本期/ }).hasAttribute('disabled')).toBe(true);
  });

  /*
   * The three ways in are a sequence -- a method is written once, a period runs
   * against it, a question comes back to the window that period locked -- and
   * three nouns in a list say none of that. Each step carries a drawing of what
   * it produces, and the arrows between them are the product's own order.
   */
  it('draws each step rather than only naming it', async () => {
    const Guide = await guide();
    const { container } = render(
      <Guide busy={false} canStart onStart={() => {}} onDismiss={() => {}} />,
    );
    expect(container.querySelectorAll('svg.fnd-step__art')).toHaveLength(3);
    // Two arrows for three steps: they carry the order, so one fewer than the
    // things being ordered.
    expect(container.querySelectorAll('svg.fnd-arrow')).toHaveLength(2);
  });

  it('draws them with one pen', async () => {
    // Monoline: one weight, no fill, round ends. A sketch that mixed weights
    // would read as an icon set rather than as one drawing.
    const Guide = await guide();
    const { container } = render(
      <Guide busy={false} canStart onStart={() => {}} onDismiss={() => {}} />,
    );
    const pens = [...container.querySelectorAll('svg g')];
    expect(pens.length).toBeGreaterThan(0);
    for (const pen of pens) {
      expect(pen.getAttribute('stroke-width')).toBe('1.4');
      expect(pen.getAttribute('fill')).toBe('none');
      expect(pen.getAttribute('stroke-linecap')).toBe('round');
    }
  });

  it('lists the three ways in, with the preset each one opens on', async () => {
    const Guide = await guide();
    render(<Guide busy={false} canStart onStart={() => {}} onDismiss={() => {}} />);
    expect(screen.getByText(/period · 开窗 导入 锁 出稿/)).toBeTruthy();
    expect(screen.getByText(/f3 · 只有 query-locked/)).toBeTruthy();
  });
});

describe('a workbench whose runtime has not answered', () => {
  it('says the product is starting rather than drawing nothing', async () => {
    // The view that covers this area is not there yet, and a window that draws
    // nothing for the seconds a cold start takes reads as one that did not open.
    const { Booting } = await import('../src/views/Workbench.js');
    render(<Booting />);
    expect(screen.getByText('FA Foundry 正在启动')).toBeTruthy();
  });
});

/*
 * The complaint this answers: the gallery listed time, task, kind, cause, size
 * and digest, and opened nothing. That is a log with better column headings.
 */
describe('reading a deliverable', () => {
  const DOC = [
    '# 本期计算底稿',
    '',
    '窗口: 96fa6c11c74e4eeb9c5748927ad18be6',
    '锁哈希: coa=04485de8 proj_ar=4725627a proj_billed=59f3b710',
    '本文件由锁库算出，不是模型起草。',
    '',
    '## q-billed · 本年账单合计多少？',
    '',
    '来源: brief',
    '标签: 我重算',
    '我重算: 282670.7525',
    '',
    '| 科目 | 辅助 | 金额 | 对照 |',
    '| --- | --- | --- | --- |',
    '| 9101 本年账单含税 | unit/上海城市公司 | 10212.6518 | 源表行 |',
    '| 9101 本年账单含税 | unit/杭州城市公司 | 8172.7051 | 源表行 |',
  ].join('\n');

  it('reads the grammar this product actually writes', async () => {
    const { readDocument } = await import('../src/components/Reader.js');
    const kinds = readDocument(DOC).map((block) => block.kind);
    expect(kinds).toEqual(['title', 'meta', 'locks', 'text', 'section', 'meta', 'table']);
  });

  it('pulls the lock digests apart instead of printing the wall', async () => {
    // One sha per table in the window, twenty-five of them in a real close. It
    // is what makes the figures reproducible, so it is kept whole.
    const { readDocument } = await import('../src/components/Reader.js');
    const locks = readDocument(DOC).find((block) => block.kind === 'locks');
    expect(locks).toBeTruthy();
    if (locks?.kind !== 'locks') throw new Error('no locks block');
    expect(locks.entries).toEqual([
      ['coa', '04485de8'],
      ['proj_ar', '4725627a'],
      ['proj_billed', '59f3b710'],
    ]);
  });

  it('drops the separator row rather than drawing it as data', async () => {
    const { readDocument } = await import('../src/components/Reader.js');
    const table = readDocument(DOC).find((block) => block.kind === 'table');
    if (table?.kind !== 'table') throw new Error('no table block');
    expect(table.head).toEqual(['科目', '辅助', '金额', '对照']);
    expect(table.rows).toHaveLength(2);
    expect(table.rows[0][2]).toBe('10212.6518');
  });

  it('keeps a line it does not recognise rather than dropping it', async () => {
    // A line added upstream should surface as text, not disappear.
    const { readDocument } = await import('../src/components/Reader.js');
    const blocks = readDocument('# t\n> 一句新加的话');
    expect(blocks[1]).toEqual({ kind: 'text', text: '> 一句新加的话' });
  });

  it('draws the table as a table', async () => {
    const { Reader } = await import('../src/components/Reader.js');
    const { container } = render(<Reader source={DOC} />);
    expect(container.querySelectorAll('table')).toHaveLength(1);
    expect(container.querySelectorAll('tbody tr')).toHaveLength(2);
    expect(container.querySelectorAll('.fnd-doc__section')).toHaveLength(1);
    expect(container.querySelector('pre')).toBeNull();
  });

  it('opens the version the operator clicked', () => {
    const opened: string[] = [];
    render(
      <Deliverables
        rows={[{ task: TASK, row: ROW }]}
        open={null}
        onOpen={(task, row) => opened.push(`${task.id}:${row.sha256}`)}
        onOpenWorkbook={() => {}}
        onExport={() => {}}
        busy={null}
        onBack={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /打开/ }));
    expect(opened).toEqual([`${TASK.id}:${ROW.sha256}`]);
  });

  it('names the version above it, so it can be placed', () => {
    // A brief read without its cause and its digest is a document an operator
    // cannot place, and placing it is why every version is kept.
    render(
      <Deliverables
        rows={[{ task: TASK, row: ROW }]}
        open={{ task: TASK, row: ROW, text: '# 本期结论稿' }}
        onOpen={() => {}}
        onOpenWorkbook={() => {}}
        onExport={() => {}}
        busy={null}
        onBack={() => {}}
      />,
    );
    expect(screen.getByText('query-locked:followup-1')).toBeTruthy();
    expect(screen.getByText('cccccccccccc')).toBeTruthy();
    expect(screen.getByText('本期结论稿')).toBeTruthy();
  });

  it('shows the header while the store is still being read', () => {
    render(
      <Deliverables
        rows={[{ task: TASK, row: ROW }]}
        open={{ task: TASK, row: ROW, text: null }}
        onOpen={() => {}}
        onOpenWorkbook={() => {}}
        onExport={() => {}}
        busy={null}
        onBack={() => {}}
      />,
    );
    expect(screen.getByText(/正在读取这一版/)).toBeTruthy();
    expect(screen.getByText('query-locked:followup-1')).toBeTruthy();
  });
});

describe('reading a workpaper', () => {
  it('draws the tag row as marks, so the cited line is not the same ink as the computed one', () => {
    const { container } = render(
      <Reader
        source={[
          '## q1 · 本期应收账款合计',
          '',
          '标签: 我重算',
          '我重算: 5000',
          '',
          '## ref-1 · 行业收缴率中位数 92.4%',
          '',
          '标签: 外部引用',
          '来源出处: 中指研究院',
          '查到于: 2026-08-30',
        ].join('\n')}
      />,
    );
    const marks = [...container.querySelectorAll('.fnd-chip')].map(
      (node) => node.getAttribute('data-mark'),
    );
    expect(marks).toEqual(['recomputed', 'external']);
    // The figure itself stays prose -- only the tag row becomes chips.
    expect(screen.getByText('5000')).toBeTruthy();
    expect(screen.getByText('中指研究院')).toBeTruthy();
  });
});

describe('a workbook version', () => {
  const BOOK: DeliverableRow = {
    ...ROW,
    kind: 'export',
    ext: '.xlsx',
    cause: 'export:xlsx',
    sha256: 'd'.repeat(64),
  };

  it('is listed as a spreadsheet rather than as a document', () => {
    render(<Deliverables rows={[{ task: TASK, row: BOOK }]} {...GALLERY} />);
    expect(screen.getByText('表格')).toBeTruthy();
  });

  it('offers the handoff instead of pushing it through the reader', () => {
    // It was written as a spreadsheet so it could be sorted and pivoted in the
    // software the operator already has. Drawing it again here would be a
    // worse copy of that software.
    const opened: number[] = [];
    render(
      <Deliverables
        rows={[{ task: TASK, row: BOOK }]}
        open={{ task: TASK, row: BOOK, text: null }}
        onOpen={() => {}}
        onOpenWorkbook={() => opened.push(1)}
        onExport={() => {}}
        busy={null}
        onBack={() => {}}
      />,
    );
    // Not the loading line: nothing is being read, and saying so would be a lie
    // that never resolves.
    expect(screen.queryByText(/正在读取这一版/)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /在表格软件里打开/ }));
    expect(opened).toEqual([1]);
  });

  it('still names the version above it', () => {
    render(
      <Deliverables
        rows={[{ task: TASK, row: BOOK }]}
        open={{ task: TASK, row: BOOK, text: null }}
        onOpen={() => {}}
        onOpenWorkbook={() => {}}
        onExport={() => {}}
        busy={null}
        onBack={() => {}}
      />,
    );
    expect(screen.getByText('export:xlsx')).toBeTruthy();
    expect(screen.getByText('dddddddddddd')).toBeTruthy();
  });

  it('reads a row with no ext as the markdown it is', () => {
    // Every version filed before workbooks existed.
    expect(isWorkbook(ROW)).toBe(false);
    expect(isWorkbook(BOOK)).toBe(true);
  });
});

describe('the task screen', () => {
  const WINDOW = {
    window_id: 'b'.repeat(32),
    reason: 'initial' as const,
    at: '2026-08-30T03:00:00Z',
    state: 'Briefed',
    inputs: [],
  };
  const DETAIL = {
    task: { ...TASK },
    windows: [WINDOW],
    sessions: [],
    deliverables: [ROW],
  };
  const PROPS = {
    onBack: () => {},
    onRead: () => {},
    onExport: () => {},
    onOpenWorkbook: () => {},
    busy: null,
    reading: null,
  };

  it('offers to write the window as a workbook, and says which window', () => {
    const asked: string[] = [];
    render(<TaskDetail detail={DETAIL} {...PROPS} onExport={(id) => asked.push(id)} />);
    fireEvent.click(screen.getByRole('button', { name: /导出 Excel/ }));
    expect(asked).toEqual([WINDOW.window_id]);
  });

  it('says it is working, on that window only', () => {
    // Writing a real close is not instant, and a button that looked idle would
    // be clicked again.
    render(<TaskDetail detail={DETAIL} {...PROPS} busy={WINDOW.window_id} />);
    const button = screen.getByRole('button', { name: /正在导出/ });
    expect((button as HTMLButtonElement).disabled).toBe(true);
  });

  it('hands a filed workbook over instead of reading it', () => {
    const book = { ...ROW, kind: 'export' as const, ext: '.xlsx', sha256: 'e'.repeat(64) };
    const read: string[] = [];
    const handed: string[] = [];
    render(
      <TaskDetail
        detail={{ ...DETAIL, deliverables: [book] }}
        {...PROPS}
        onRead={(sha) => read.push(sha)}
        onOpenWorkbook={(sha, ext) => handed.push(`${sha}${ext}`)}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /在表格软件里打开/ }));
    expect(read).toEqual([]);
    expect(handed).toEqual([`${book.sha256}.xlsx`]);
  });
});

describe('finding the export at all', () => {
  /*
   * The defect this pins was measured in the packaged app, not imagined. The
   * only export action lived on the task screen, below 输入归档 -- which on a
   * real close is twenty-odd rows each carrying a full source path. Its button
   * sat 1344px below the fold of an 828px viewport, and the screen actually
   * named 交付物 had no export at all. An action nobody can scroll to is an
   * action that does not exist.
   */
  it('offers it on the screen named 交付物, while reading a document', () => {
    const asked: string[] = [];
    render(
      <Deliverables
        rows={[{ task: TASK, row: ROW }]}
        open={{ task: TASK, row: ROW, text: '# 本期结论稿' }}
        onOpen={() => {}}
        onOpenWorkbook={() => {}}
        onExport={(task, windowId) => asked.push(`${task.id}:${windowId}`)}
        busy={null}
        onBack={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /导出 Excel/ }));
    expect(asked).toEqual([`${TASK.id}:${ROW.window_id}`]);
  });

  it('does not offer to export a workbook into a workbook', () => {
    const book: DeliverableRow = { ...ROW, kind: 'export', ext: '.xlsx' };
    render(
      <Deliverables
        rows={[{ task: TASK, row: book }]}
        open={{ task: TASK, row: book, text: null }}
        onOpen={() => {}}
        onOpenWorkbook={() => {}}
        onExport={() => {}}
        busy={null}
        onBack={() => {}}
      />,
    );
    expect(screen.queryByRole('button', { name: /导出 Excel/ })).toBeNull();
    expect(screen.getByRole('button', { name: /在表格软件里打开/ })).toBeTruthy();
  });

  it('sits above the input archive on the task screen, not below it', () => {
    // Order is the whole fix, so order is what is asserted -- on the rendered
    // DOM rather than the source, because what went wrong was a position on
    // screen and not a position in a file.
    render(
      <TaskDetail
        detail={{
          task: { ...TASK },
          windows: [
            {
              window_id: 'b'.repeat(32),
              reason: 'initial' as const,
              at: '2026-08-30T03:00:00Z',
              state: 'Briefed',
              inputs: [],
            },
          ],
          sessions: [],
          deliverables: [],
        }}
        onBack={() => {}}
        onRead={() => {}}
        onExport={() => {}}
        onOpenWorkbook={() => {}}
        busy={null}
        reading={null}
      />,
    );
    const action = screen.getByRole('button', { name: /导出 Excel/ });
    const archive = screen.getByRole('heading', { name: /输入归档/ });
    expect(archive).toBeTruthy();
    // DOCUMENT_POSITION_FOLLOWING === 4: the archive comes after the button.
    expect(action.compareDocumentPosition(archive!) & 4).toBe(4);
  });
});

describe('the export button can be read', () => {
  /*
   * Outline actions used to fall through to the user agent when `.fnd-button`
   * was missing. Thin controls now live on the Button primitive; they still
   * have to take colour from FA tokens so both themes stay legible.
   */
  const button = readFileSync(resolve(process.cwd(), 'src/components/ui/button.tsx'), 'utf8');

  it('skins outline actions with FA tokens rather than a second palette', () => {
    expect(button).toContain('border-border');
    expect(button).toContain('bg-transparent');
    expect(button).toContain('text-foreground');
    expect(button).toContain('var(--fnd-line-hover)');
    expect(button).not.toMatch(/#[0-9a-f]{3,8}/i);
  });

  it('does not add a hover fill on the primary action', () => {
    expect(button).not.toContain('hover:bg-primary/90');
  });

  it('colours irreversible delete with the warning colour, not the gold', () => {
    expect(button).toContain('var(--fnd-warning)');
    expect(button).not.toContain('var(--fnd-mark-outside)');
    expect(button).not.toContain('bg-destructive text-white');
  });

  it('says it is disabled while the workbook is being written', () => {
    expect(button).toContain('disabled:opacity-55');
  });

  // Focus + hover and primary contrast are verified using computed styles in
  // tools/verify_control_states.cjs. A single CSS rule cannot prove the cascade.
});

describe('looking at a workbook without leaving the window', () => {
  const BOOK: DeliverableRow = {
    ...ROW,
    kind: 'export',
    ext: '.xlsx',
    cause: 'export:xlsx',
    sha256: 'd'.repeat(64),
  };

  it('offers the look beside the handoff on the screen named 交付物', () => {
    const asked: string[] = [];
    render(
      <Deliverables
        rows={[{ task: TASK, row: BOOK }]}
        open={{ task: TASK, row: BOOK, text: null }}
        onOpen={() => {}}
        onOpenWorkbook={() => {}}
        onPreview={(task, row) => asked.push(`${task.id}:${row.sha256}`)}
        onExport={() => {}}
        busy={null}
        onBack={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /在这里预览/ }));
    expect(asked).toEqual([`${TASK.id}:${BOOK.sha256}`]);
    expect(screen.getByRole('button', { name: /在表格软件里打开/ })).toBeTruthy();
  });

  it('says it is working on that version, and only that one', () => {
    // An import is a headless Univer coming up; seconds, not milliseconds.
    render(
      <Deliverables
        rows={[{ task: TASK, row: BOOK }]}
        open={{ task: TASK, row: BOOK, text: null }}
        onOpen={() => {}}
        onOpenWorkbook={() => {}}
        onPreview={() => {}}
        previewing={BOOK.sha256}
        onExport={() => {}}
        busy={null}
        onBack={() => {}}
      />,
    );
    expect((screen.getByRole('button', { name: /正在装进预览/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('does not offer a look a build with no viewer cannot give', () => {
    render(
      <Deliverables
        rows={[{ task: TASK, row: BOOK }]}
        open={{ task: TASK, row: BOOK, text: null }}
        onOpen={() => {}}
        onOpenWorkbook={() => {}}
        onExport={() => {}}
        busy={null}
        onBack={() => {}}
      />,
    );
    expect(screen.queryByRole('button', { name: /在这里预览/ })).toBeNull();
  });

  it('offers it on the task screen too, on each filed workbook', () => {
    const asked: string[] = [];
    render(
      <TaskDetail
        detail={{
          task: { ...TASK },
          windows: [
            {
              window_id: 'b'.repeat(32),
              reason: 'initial' as const,
              at: '2026-08-30T03:00:00Z',
              state: 'Briefed',
              inputs: [],
            },
          ],
          sessions: [],
          deliverables: [BOOK, ROW],
        }}
        onBack={() => {}}
        onRead={() => {}}
        onExport={() => {}}
        onOpenWorkbook={() => {}}
        onPreview={(sha, ext) => asked.push(`${sha}${ext}`)}
        busy={null}
        reading={null}
      />,
    );
    // One look per workbook; the markdown row beside it gets none.
    const looks = screen.getAllByRole('button', { name: /^预览 / });
    expect(looks).toHaveLength(1);
    fireEvent.click(looks[0]);
    expect(asked).toEqual([`${BOOK.sha256}.xlsx`]);
  });

  it('names the task, the version and the server in the strip, and closes from there', async () => {
    // The viewer under the strip is a native view, so a control drawn in the
    // column would be under it. The strip names the origin because the
    // operator accepted a server that lives only while the strip does.
    const { PreviewBar } = await import('../src/views/Preview.js');
    let closed = 0;
    render(
      <PreviewBar
        preview={{ task: TASK.id, sha256: BOOK.sha256, origin: 'http://127.0.0.1:9081' }}
        task={TASK}
        onClose={() => {
          closed += 1;
        }}
      />,
    );
    expect(screen.getByText('2026-08 月度经营分析')).toBeTruthy();
    expect(screen.getByText('dddddddddddd')).toBeTruthy();
    expect(screen.getByText(/http:\/\/127\.0\.0\.1:9081/)).toBeTruthy();
    expect(screen.getByText(/不落盘/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /关闭预览/ }));
    expect(closed).toBe(1);
  });

  it('stops the column scrolling under the viewer, as it does under the workbench', async () => {
    const { Shell } = await import('../src/components/Shell.js');
    const { container } = render(
      <Shell screen="deliverables" onScreen={() => {}} covered>
        <p>x</p>
      </Shell>,
    );
    expect(container.querySelector('.fnd-shell')?.getAttribute('data-embedded')).toBe('yes');
  });
});
