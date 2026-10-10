/**
 * The design system page: every token and primitive on one screen, in both themes, for checking a
 * style change by eye and by screenshot. Served by the dev server at /design-system.html only; it is
 * not a build input, so the packaged app never carries it (DESIGN.md 设计系统页).
 */
import { useEffect, useState, type ReactNode } from 'react';
import { CalendarDays, ChevronDown, FileDown, Plus, Trash2 } from 'lucide-react';

import { DisclosureSummary } from '@/components/Disclosure.js';
import { Figure } from '@/components/Figure.js';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog.js';
import { Badge } from '@/components/ui/badge.js';
import { Button } from '@/components/ui/button.js';
import { Calendar } from '@/components/ui/calendar.js';
import { Checkbox } from '@/components/ui/checkbox.js';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible.js';
import { Command, CommandInput, CommandItem, CommandList } from '@/components/ui/command.js';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu.js';
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty.js';
import { Field, FieldDescription, FieldError, FieldLabel } from '@/components/ui/field.js';
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card.js';
import { Input } from '@/components/ui/input.js';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select.js';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover.js';
import { Skeleton } from '@/components/ui/skeleton.js';
import { Switch } from '@/components/ui/switch.js';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs.js';
import { Textarea } from '@/components/ui/textarea.js';

type Theme = 'light' | 'dark';

/**
 * Any CSS colour (hex, rgb, oklch, color-mix, display-p3) as sRGB, by painting one pixel over a
 * backdrop, so translucent colours composite as the browser draws them (the shadcn skill's color-pair).
 */
function toRgb(color: string, backdrop: string): number[] | null {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 1;
  const context = canvas.getContext('2d', { willReadFrequently: true });
  if (!context) return null;
  context.fillStyle = backdrop;
  context.fillRect(0, 0, 1, 1);
  context.fillStyle = color;
  context.fillRect(0, 0, 1, 1);
  const [r, g, b] = context.getImageData(0, 0, 1, 1).data;
  return [r, g, b];
}

/** WCAG contrast of a text colour on a ground, the ground itself laid over the canvas. */
function contrast(fg: string, bg: string): number | null {
  const ground = toRgb(bg, token('--fnd-bg') || '#fff');
  const text = ground && toRgb(fg, `rgb(${ground.join(' ')})`);
  if (!ground || !text) return null;
  const lum = ([r, g, b]: number[]) => {
    const c = (v: number) => { const s = v / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * c(r) + 0.7152 * c(g) + 0.0722 * c(b);
  };
  const [light, dark] = [lum(text), lum(ground)].sort((x, y) => y - x);
  return (light + 0.05) / (dark + 0.05);
}

const token = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const GROUNDS = ['--fnd-bg', '--fnd-surface', '--fnd-surface-strong', '--fnd-selection-surface'];
const TEXT = [
  ['--fnd-ink', '正文'], ['--fnd-muted', '次要文字'], ['--fnd-selected', '金色：位置与选择'],
  ['--fnd-warning', '砖红：警示'], ['--fnd-negative', '负数暗红'], ['--fnd-level-ok', '筛查：绿'],
  ['--fnd-level-watch', '筛查：黄'], ['--fnd-mark-external', '外部标记'],
] as const;
const PALETTE = [
  '--fnd-bg', '--fnd-surface', '--fnd-surface-strong', '--fnd-selection-surface', '--fnd-ink', '--fnd-muted',
  '--fnd-line', '--fnd-line-hover', '--fnd-accent', '--fnd-selected', '--fnd-focus', '--fnd-warning',
  '--fnd-warning-line', '--fnd-warning-fill', '--fnd-negative', '--fnd-level-ok', '--fnd-level-watch', '--fnd-mark-external',
];
const SIZES = [
  ['label', '12'], ['small', '13'], ['body', '14'], ['h3', '16'], ['lead', '18'], ['title', '20'],
  ['conclusion', '22'], ['h2', '24'], ['display', '28'],
] as const;
const STATES = ['default', 'hover', 'focus', 'active', 'disabled'] as const;

function pin(state: string) {
  if (state === 'disabled') return { disabled: true };
  return state === 'default' ? {} : { 'data-preview': state };
}

function Section({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return <section><h2>{title}</h2>{note ? <p className="ds__note">{note}</p> : null}{children}</section>;
}

function Pairs({ theme }: { theme: Theme }) {
  const [, redraw] = useState(0);
  // Read the tokens after the theme stamp has applied.
  useEffect(() => { redraw((n) => n + 1); }, [theme]);
  return <div className="ds__grid">
    {TEXT.flatMap(([name, label]) => GROUNDS.map((ground) => {
      const ratio = contrast(token(name), token(ground));
      return <div key={`${name}${ground}`} className="ds__pair" style={{ background: `var(${ground})`, color: `var(${name})` }}>
        <span>{label}</span>
        <span className="ds__ratio" data-low={ratio !== null && ratio < 4.5 ? '' : undefined}>{ratio === null ? '—' : `${ratio.toFixed(2)}:1`}</span>
        <small>{name} / {ground}</small>
      </div>;
    }))}
  </div>;
}

export function DesignSystem() {
  const [theme, setTheme] = useState<Theme>(() => (window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));
  const [day, setDay] = useState<Date | undefined>(new Date(2026, 7, 31));
  const [picked, setPicked] = useState('none');
  const [confirming, setConfirming] = useState(false);
  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);

  return <main className="ds">
    <header className="ds__head">
      <div>
        <h1>FA Foundry 设计系统</h1>
        <p>冷画布、白卡片、金色只标位置。这一页只在开发服务器上有，打包版不带。</p>
      </div>
      <Tabs value={theme} onValueChange={(value) => setTheme(value as Theme)}>
        <TabsList><TabsTrigger value="light">浅色</TabsTrigger><TabsTrigger value="dark">深色</TabsTrigger></TabsList>
      </Tabs>
    </header>

    <Section title="颜色角色" note="每种文字色在四种底上的对比度。低于 4.5:1 的标红，这种组合不能用作文字（例如筛查黄只放在画布和卡片上）；金色在选择底上压着 4.5 的下限。">
      <Pairs theme={theme} />
    </Section>

    <Section title="色板">
      <div className="ds__grid">
        {PALETTE.map((name) => <div key={name} className="ds__swatch">
          <span style={{ background: `var(${name})` }} />
          <code>{name}</code>
        </div>)}
      </div>
    </Section>

    <Section title="字号" note="九档，最小 12px；中文用 Noto Sans SC，数字用 IBM Plex Mono，都不动。">
      <div>
        {SIZES.map(([name, px]) => <div key={name} className="ds__type">
          <code>--fnd-size-{name} · {px}px</code>
          <span style={{ fontSize: `var(--fnd-size-${name})` }}>华宸物业 8 月收缴率 <Figure text="82.12%" /></span>
        </div>)}
        <div className="ds__type"><code>figure · 负数</code><span><Figure text="(18,843.06)" /> <Figure text="1,234,567.89" /></span></div>
      </div>
    </Section>

    <Section title="圆角、阴影与间距" note="圆角四档；阴影三档，带午夜蓝色调；间距 4px 网格。">
      <div className="ds__ladder">
        {['mark', 'control', 'container', 'pill'].map((name) => <div key={name}>
          <span className="ds__shape" style={{ borderRadius: `var(--fnd-radius-${name})` }} />--fnd-radius-{name}
        </div>)}
      </div>
      <div className="ds__ladder">
        {['sm', 'md', 'lg'].map((name) => <div key={name}>
          <span className="ds__shape" style={{ border: 0, borderRadius: 'var(--fnd-radius-container)', boxShadow: `var(--fnd-shadow-${name})` }} />--fnd-shadow-{name}
        </div>)}
      </div>
      <div className="ds__ladder">
        {[4, 8, 12, 16, 20, 24, 32, 48].map((px) => <div key={px}><span className="ds__space" style={{ width: px }} />{px}</div>)}
      </div>
    </Section>

    <Section title="按钮" note="状态用 data-preview 钉住，不用鼠标就能看到悬停、焦点和按下。">
      <div className="ds__card">
        <table className="ds__matrix">
          <thead><tr><th />{STATES.map((state) => <th key={state} scope="col">{state}</th>)}</tr></thead>
          <tbody>
            {(['default', 'outline', 'secondary', 'ghost', 'destructive', 'link'] as const).map((variant) => <tr key={variant}>
              <th scope="row">{variant}</th>
              {STATES.map((state) => <td key={state}>
                <Button variant={variant} {...pin(state)}>{variant === 'destructive' ? <Trash2 size={14} aria-hidden /> : null}保存</Button>
              </td>)}
            </tr>)}
            <tr>
              <th scope="row">chip</th>
              {STATES.map((state) => <td key={state}><Button variant="outline" size="chip" {...pin(state)}>2026 年 8 月</Button></td>)}
            </tr>
          </tbody>
        </table>
        <div className="ds__row">
          <Button><Plus size={14} aria-hidden />新建任务</Button>
          <Button variant="outline" size="sm"><FileDown size={14} aria-hidden />导出</Button>
          <Button variant="ghost" size="icon" aria-label="打开日期"><CalendarDays size={16} aria-hidden /></Button>
          <Button variant="outline" size="chip" aria-pressed="true">已选 chip</Button>
          <Badge>当前版</Badge><Badge variant="secondary">示例</Badge><Badge variant="destructive">3 处不一致</Badge>
        </div>
      </div>
    </Section>

    <Section title="字段">
      <div className="ds__card">
        <div className="ds__grid">
          <Field><FieldLabel htmlFor="ds-name">任务名</FieldLabel><Input id="ds-name" defaultValue="华宸物业 8 月月结" /><FieldDescription>会显示在顶栏和成果库。</FieldDescription></Field>
          <Field data-invalid><FieldLabel htmlFor="ds-amount">金额</FieldLabel><Input id="ds-amount" aria-invalid defaultValue="12,3a4" /><FieldError>只能填数字。</FieldError></Field>
          <Field><FieldLabel htmlFor="ds-unit">单位</FieldLabel><NativeSelect id="ds-unit" defaultValue="万元"><NativeSelectOption>元</NativeSelectOption><NativeSelectOption>万元</NativeSelectOption></NativeSelect></Field>
          <Field><FieldLabel htmlFor="ds-off">停用</FieldLabel><Input id="ds-off" disabled defaultValue="读取中…" /></Field>
        </div>
        <Field><FieldLabel htmlFor="ds-note">处置理由</FieldLabel><Textarea id="ds-note" defaultValue="账单年度坏账分项按应收余额逐年计提，合计取总账 1231 账龄组合数。" /></Field>
        <div className="ds__row">
          <label className="ds__row"><Checkbox defaultChecked />纳入本月</label>
          <label className="ds__row"><Checkbox />未选</label>
          <label className="ds__row"><Switch defaultChecked />接受差异后需要第二人复核</label>
          <label className="ds__row"><Switch disabled />停用的开关</label>
        </div>
      </div>
    </Section>

    <Section title="页签、折叠与空状态">
      <div className="ds__card">
        <Tabs defaultValue="materials">
          <TabsList variant="line"><TabsTrigger value="materials">资料 42</TabsTrigger><TabsTrigger value="results">分析结果 1</TabsTrigger><TabsTrigger value="close">月结</TabsTrigger></TabsList>
          <TabsContent value="materials"><p className="ds__note">下划线页签：当前页签正文色、字重 600，下面一条金线。</p></TabsContent>
          <TabsContent value="results"><p className="ds__note">分析结果</p></TabsContent>
          <TabsContent value="close"><p className="ds__note">月结</p></TabsContent>
        </Tabs>
        <details className="fnd-disclosure" open><DisclosureSummary>范围与计算</DisclosureSummary><p className="ds__note">原生 details 折叠，展开时箭头转 90°。</p></details>
        <Collapsible>
          <CollapsibleTrigger asChild><Button variant="ghost" size="sm"><ChevronDown size={14} aria-hidden />Collapsible</Button></CollapsibleTrigger>
          <CollapsibleContent><p className="ds__note">只在需要受控开合时用。</p></CollapsibleContent>
        </Collapsible>
        <Empty><EmptyHeader><EmptyTitle>还没有文稿</EmptyTitle><EmptyDescription>计算完成后，让助手起草一份。</EmptyDescription></EmptyHeader><EmptyContent><Button variant="outline">让助手起草</Button></EmptyContent></Empty>
        <div className="ds__grid"><Skeleton className="h-6" /><Skeleton className="h-6" /><Skeleton className="h-6" /></div>
      </div>
    </Section>

    <Section title="浮层" note="菜单和弹层用 shadow-md，确认对话框用 shadow-lg。">
      <div className="ds__card">
        <div className="ds__row">
          <Popover>
            <PopoverTrigger asChild><Button variant="outline"><CalendarDays size={14} aria-hidden />截至日</Button></PopoverTrigger>
            <PopoverContent className="fnd-date-picker__popover" aria-label="截至日选择"><Calendar mode="single" required selected={day} defaultMonth={day} onSelect={setDay} /></PopoverContent>
          </Popover>
          <DropdownMenu>
            <DropdownMenuTrigger asChild><Button variant="outline">更多操作</Button></DropdownMenuTrigger>
            <DropdownMenuContent><DropdownMenuGroup>
              <DropdownMenuItem>重命名</DropdownMenuItem><DropdownMenuItem>归档</DropdownMenuItem><DropdownMenuItem variant="destructive">永久删除</DropdownMenuItem>
            </DropdownMenuGroup></DropdownMenuContent>
          </DropdownMenu>
          <HoverCard>
            <HoverCardTrigger asChild><Button variant="link">收缴率口径</Button></HoverCardTrigger>
            <HoverCardContent>当期收缴率 ＝ 本年账期已收 ÷ 本年应收。</HoverCardContent>
          </HoverCard>
          <Button variant="destructive" onClick={() => setConfirming(true)}>清空回收站</Button>
          <AlertDialog open={confirming} onOpenChange={setConfirming}>
            <AlertDialogContent>
              <AlertDialogHeader><AlertDialogTitle>永久删除回收站里的 2 个任务？</AlertDialogTitle><AlertDialogDescription>删除后不能恢复。</AlertDialogDescription></AlertDialogHeader>
              <AlertDialogFooter><AlertDialogCancel>取消</AlertDialogCancel><AlertDialogAction>永久删除</AlertDialogAction></AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
        <Command value={picked} onValueChange={setPicked} label="科目搜索" className="max-w-sm rounded-[var(--fnd-radius-container)] border border-[var(--fnd-line)]">
          <CommandInput aria-label="科目搜索" placeholder="搜索名称或编码" />
          <CommandList><CommandItem value="1122">1122 应收账款</CommandItem><CommandItem value="1231">1231 坏账准备</CommandItem></CommandList>
        </Command>
      </div>
    </Section>

    <Section title="该做与不该做">
      <div className="ds__dodont">
        <div data-kind="do"><strong>该做：金色只标位置</strong><Tabs defaultValue="a"><TabsList variant="line"><TabsTrigger value="a">资料</TabsTrigger><TabsTrigger value="b">结果</TabsTrigger></TabsList></Tabs></div>
        <div data-kind="dont"><strong>不该做：警示用金色</strong><span style={{ color: 'var(--fnd-selected)' }}>3 处不一致</span></div>
        <div data-kind="do"><strong>该做：画布上的卡片用细线加 shadow-sm</strong><div className="ds__card">KPI 卡</div></div>
        <div data-kind="dont"><strong>不该做：主按钮做成通栏或胶囊</strong><Button className="w-full rounded-full">提交</Button></div>
      </div>
    </Section>
  </main>;
}
