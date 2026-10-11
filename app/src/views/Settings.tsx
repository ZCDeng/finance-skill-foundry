import { useEffect, useId, useState, type FormEvent, type ReactNode } from 'react';
import { FolderOpen, UserPlus } from 'lucide-react';
import { bridge, type Preferences } from '../bridge.js';
import { usePreferences } from '../components/Preferences.js';
import { ThemeSwitch } from '../components/ThemeSwitch.js';
import { Button } from '../components/ui/button.js';
import { Input } from '../components/ui/input.js';
import { NativeSelect } from '../components/ui/native-select.js';
import { Switch } from '../components/ui/switch.js';
import './settings.css';

type Person = Preferences['people'][number];
const ROLE_WORDS: Record<Person['role'], string> = { manager: '经理', analyst: '财务分析', reviewer: '复核人' };
/** As many as electron/preferences.ts keeps. */
const MAX_PEOPLE = 20;

/**
 * 设置: what the manager chooses for the app as a whole, on this computer. One page, reached from the gear in the
 * header or ⌘/Ctrl + ,. The model and its key stay in the conversation pane's own gear, where the harness keeps them.
 */
export function Settings({ onWorkspace }: { onWorkspace(): void }) {
  const api = bridge();
  const { preferences, available, set } = usePreferences();
  const [problem, setProblem] = useState('');
  const [info, setInfo] = useState<{ version: string; data_folder: string } | null>(null);
  useEffect(() => {
    if (!api?.appInfo) return;
    let live = true;
    void api.appInfo().then((answer) => { if (live && answer.ok) setInfo(answer.value); }).catch(() => {});
    return () => { live = false; };
  }, [api]);
  const change = (patch: Parameters<typeof set>[0]) => {
    setProblem('');
    void set(patch).catch((failure: unknown) => setProblem(`没有保存：${failure instanceof Error ? failure.message : String(failure)}`));
  };
  const reveal = () => {
    setProblem('');
    void api?.appRevealData?.().then((answer) => { if (!answer.ok) setProblem(`打不开数据目录：${answer.message}`); })
      .catch((failure: unknown) => setProblem(`打不开数据目录：${failure instanceof Error ? failure.message : String(failure)}`));
  };

  return <div className="fnd-settings">
    <div className="fnd-settings__head">
      <h1 className="fnd-settings__title">设置</h1>
      <p className="fnd-muted">这些选择只在这台电脑上生效。</p>
    </div>
    {!available ? <p className="fnd-settings__notice" role="note">当前安装版还不能保存设置，更新后即可使用。</p> : null}
    {problem ? <p className="fnd-settings__notice" role="alert">{problem}</p> : null}

    <Section title="通用">
      <Row label="外观" note="跟随系统、浅色或深色。">
        <ThemeSwitch />
      </Row>
      <Row label="打开应用时进入" note="总览看本月进度和待办；工作区直接进入任务和对话。">
        {(id) => <NativeSelect id={id} className="fnd-settings__select" value={preferences.start} disabled={!available}
          onChange={(event) => change({ start: event.target.value === 'workspace' ? 'workspace' : 'overview' })}>
          <option value="overview">总览</option>
          <option value="workspace">工作区</option>
        </NativeSelect>}
      </Row>
    </Section>

    <Section title="使用者">
      <People available={available} people={preferences.people} current={preferences.current_person} change={change} />
    </Section>

    <Section title="显示">
      <Row label="显示技术信息" note="编号、摘要、脚本、SQL、原始结果和引擎诊断。平时用不到，排查问题时再打开；助手不受影响，照常能读。">
        {(id) => <Switch id={id} checked={preferences.technical} disabled={!available} onCheckedChange={(on) => change({ technical: on })} />}
      </Row>
      <Row label="本月三句话默认展开" note="打开任务时，顶部的本月三句话展开显示；关掉后收成一行，点开再看。">
        {(id) => <Switch id={id} checked={preferences.brief_open} disabled={!available} onCheckedChange={(on) => change({ brief_open: on })} />}
      </Row>
    </Section>

    <Section title="助手">
      <Row label="模型和密钥" note="在工作区对话窗格右上角的齿轮里设置。换模型不影响已经保存的结果和文稿。">
        <Button variant="outline" size="sm" type="button" onClick={onWorkspace}>去工作区</Button>
      </Row>
    </Section>

    <Section title="数据与存储">
      <Row label="数据目录" note={info ? <span className="fnd-settings__path">{info.data_folder}</span> : '任务、资料快照、计算记录和文稿都存在这里，只在这台电脑上。'}>
        {api?.appRevealData ? <Button variant="outline" size="sm" type="button" onClick={reveal}>
          <FolderOpen size={14} strokeWidth={1.5} aria-hidden />在访达中显示</Button> : null}
      </Row>
    </Section>

    <Section title="关于">
      <Row label="FA Foundry" note={info ? `版本 ${info.version}` : '可追溯的 AI 财务分析师。'} />
    </Section>
  </div>;
}

/**
 * 使用者 on this computer: a name, what they do and the 署名 a record is signed with, and who is signing now. Disposing
 * of a difference, its review, a board card's 认可 and the one-page board fill that 署名 in, and it can still be changed
 * there. There is no password: this is who signed, not who may.
 */
function People({ available, people, current, change }: {
  available: boolean; people: Person[]; current: string; change(patch: Partial<Preferences>): void;
}) {
  // The person being changed, or 'new' for one being added; null while the list is only read.
  const [editing, setEditing] = useState<string | null>(null);
  const signing = people.some((person) => person.id === current) ? current : '';
  const save = (person: Person) => {
    const known = people.some((row) => row.id === person.id);
    change({ people: known ? people.map((row) => (row.id === person.id ? person : row)) : [...people, person],
      // The first person added signs from then on; nobody has to pick them as well.
      ...(!known && !people.length ? { current_person: person.id } : {}) });
    setEditing(null);
  };
  const remove = (person: Person) => change({ people: people.filter((row) => row.id !== person.id), ...(person.id === current ? { current_person: '' } : {}) });
  return <>
    <Row label="当前使用者" note="处置差异、复核、认可看板卡和导出一页纸时，自动填上这个人的署名，填上后仍可改。同一台电脑上切换使用者不要密码：这是署名，不是权限。">
      {(id) => <NativeSelect id={id} className="fnd-settings__select" value={signing} disabled={!available || !people.length}
        onChange={(event) => change({ current_person: event.target.value })}>
        <option value="">没有选（每次自己填）</option>
        {people.map((person) => <option key={person.id} value={person.id}>{`${person.name} · ${ROLE_WORDS[person.role]}`}</option>)}
      </NativeSelect>}
    </Row>
    {people.map((person) => editing === person.id
      ? <PersonForm key={person.id} person={person} onSave={save} onCancel={() => setEditing(null)} />
      : <Row key={person.id} label={person.name} note={`${ROLE_WORDS[person.role]} · 署名「${person.signature}」${person.id === signing ? ' · 当前使用者' : ''}`}>
        <Button variant="ghost" size="sm" type="button" disabled={!available || editing !== null} onClick={() => setEditing(person.id)}
          aria-label={`改「${person.name}」`}>改</Button>
        <Button variant="ghost" size="sm" type="button" disabled={!available || editing !== null} onClick={() => remove(person)}
          aria-label={`删除「${person.name}」`}>删除</Button>
      </Row>)}
    {editing === 'new' ? <PersonForm onSave={save} onCancel={() => setEditing(null)} />
      : people.length < MAX_PEOPLE ? <Row label={people.length ? '再加一个人' : '还没有使用者'} note={people.length ? undefined : '加上自己，以后署名不用每次手填。'}>
        <Button variant="outline" size="sm" type="button" disabled={!available || editing !== null} onClick={() => setEditing('new')}>
          <UserPlus size={14} strokeWidth={1.5} aria-hidden />添加使用者</Button>
      </Row> : null}
  </>;
}

function PersonForm({ person, onSave, onCancel }: { person?: Person; onSave(person: Person): void; onCancel(): void }) {
  const id = useId();
  const [name, setName] = useState(person?.name ?? '');
  const [role, setRole] = useState<Person['role']>(person?.role ?? 'manager');
  const [signature, setSignature] = useState(person?.signature ?? '');
  const tidy = (text: string) => text.replace(/\s+/g, ' ').trim();
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!tidy(name)) return;
    onSave({ id: person?.id ?? crypto.randomUUID().replace(/-/g, ''), name: tidy(name), role, signature: tidy(signature) || tidy(name) });
  };
  return <form className="fnd-settings__row fnd-settings__person" aria-label={person ? `改「${person.name}」` : '添加使用者'} onSubmit={submit}>
    <div className="fnd-settings__fields">
      <label htmlFor={`${id}-name`}>姓名</label>
      <Input id={`${id}-name`} value={name} maxLength={80} required onChange={(event) => setName(event.target.value)} />
      <label htmlFor={`${id}-role`}>角色</label>
      <NativeSelect id={`${id}-role`} value={role} onChange={(event) => setRole(event.target.value as Person['role'])}>
        {(Object.keys(ROLE_WORDS) as Person['role'][]).map((key) => <option key={key} value={key}>{ROLE_WORDS[key]}</option>)}
      </NativeSelect>
      <label htmlFor={`${id}-signature`}>署名</label>
      <Input id={`${id}-signature`} value={signature} maxLength={80} placeholder={tidy(name) || '和姓名一样'} onChange={(event) => setSignature(event.target.value)} />
    </div>
    <div className="fnd-settings__control">
      <Button size="sm" type="submit" disabled={!tidy(name)}>{person ? '保存' : '添加'}</Button>
      <Button variant="ghost" size="sm" type="button" onClick={onCancel}>取消</Button>
    </div>
  </form>;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  const id = useId();
  return <section className="fnd-settings__section" aria-labelledby={id}>
    <h2 className="fnd-settings__h" id={id}>{title}</h2>
    <div className="fnd-settings__rows">{children}</div>
  </section>;
}

/** One choice: what it is and what it does on the left, the control on the right, labelled by the left. */
function Row({ label, note, children }: { label: string; note?: ReactNode; children?: ReactNode | ((id: string) => ReactNode) }) {
  const id = useId();
  const control = typeof children === 'function' ? children(id) : children;
  return <div className="fnd-settings__row">
    <div className="fnd-settings__text">
      {typeof children === 'function' ? <label className="fnd-settings__label" htmlFor={id}>{label}</label>
        : <p className="fnd-settings__label">{label}</p>}
      {note ? <p className="fnd-settings__note">{note}</p> : null}
    </div>
    {control ? <div className="fnd-settings__control">{control}</div> : null}
  </div>;
}
