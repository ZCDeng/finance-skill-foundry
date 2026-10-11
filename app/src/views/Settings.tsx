import { useEffect, useId, useState, type ReactNode } from 'react';
import { FolderOpen } from 'lucide-react';
import { bridge } from '../bridge.js';
import { usePreferences } from '../components/Preferences.js';
import { ThemeSwitch } from '../components/ThemeSwitch.js';
import { Button } from '../components/ui/button.js';
import { NativeSelect } from '../components/ui/native-select.js';
import { Switch } from '../components/ui/switch.js';
import './settings.css';

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
