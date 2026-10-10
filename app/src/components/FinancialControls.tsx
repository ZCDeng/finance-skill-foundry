import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode, type RefObject } from 'react';
import { CalendarDays, Check, ChevronDown, ChevronLeft, ChevronRight, X } from 'lucide-react';
import { Calendar } from './ui/calendar.js';
import { Command, CommandInput, CommandItem, CommandList } from './ui/command.js';
import { Field, FieldDescription, FieldError, FieldLabel, FieldTitle } from './ui/field.js';
import { Input } from './ui/input.js';
import { Button } from './ui/button.js';
import { Popover, PopoverAnchor, PopoverContent, PopoverTrigger } from './ui/popover.js';
import { searchKey } from '../lib/search.js';
import './financial-controls.css';

export type SelectOption = {
  value: string;
  label: string;
  meta?: string;
  /** Also matched by the search, never shown: a stored value the meta writes in words (2026-08). */
  keywords?: string;
  disabled?: boolean;
};

type FieldShellProps = {
  label: string;
  htmlFor?: string;
  hideLabel?: boolean;
  help?: string;
  error?: string;
  disabledReason?: string;
  required?: boolean;
  children: ReactNode;
};

function fieldDescribedBy(id: string, ...messages: Array<string | undefined | false>) {
  return messages.some(Boolean) ? `${id}-description` : undefined;
}

export function FieldShell({ label, htmlFor, hideLabel, help, error, disabledReason, required, children }: FieldShellProps) {
  const hasMessage = Boolean(error || disabledReason || help);
  const descriptionId = htmlFor && hasMessage ? `${htmlFor}-description` : undefined;
  const mark = required ? <span aria-hidden> *</span> : null;
  return <Field data-invalid={error ? 'true' : undefined}>
    {!hideLabel && (htmlFor ? <FieldLabel htmlFor={htmlFor}>{label}{mark}</FieldLabel> : <FieldTitle>{label}{mark}</FieldTitle>)}
    {children}
    {hasMessage && (error
      ? <FieldError id={descriptionId}>{error}</FieldError>
      : <FieldDescription id={descriptionId}>{disabledReason || help}</FieldDescription>)}
  </Field>;
}

export function TextField({ label, value, onChange, placeholder, help, error, disabled, ariaLabel, inputMode }: {
  label: string; value: string; onChange(value: string): void; placeholder?: string; help?: string; error?: string; disabled?: boolean; ariaLabel?: string;
  inputMode?: 'decimal' | 'numeric' | 'text';
}) {
  const id = useId();
  return <FieldShell label={label} htmlFor={id} help={help} error={error}>
    <Input id={id} aria-label={ariaLabel ?? label} aria-describedby={fieldDescribedBy(id, help, error)} aria-invalid={error ? true : undefined} value={value} placeholder={placeholder}
      inputMode={inputMode} disabled={disabled} onChange={(event) => onChange(event.target.value)} />
  </FieldShell>;
}

const validPeriod = (value: string) => /^\d{4}-(0[1-9]|1[0-2])$/.test(value);
const validDate = (value: string) => {
  if (!/^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/.test(value)) return false;
  const [year, month, day] = value.split('-').map(Number);
  const date = new Date(year, month - 1, day);
  return date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === day;
};
const pad = (value: number) => String(value).padStart(2, '0');
const toPeriod = (date: Date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}`;
const toDateText = (date: Date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
const currentPeriod = () => toPeriod(new Date());
const previousPeriod = (value: string) => {
  const base = validPeriod(value) ? value : currentPeriod();
  const [year, month] = base.split('-').map(Number);
  return toPeriod(new Date(year, month - 2, 1));
};
const lastYearPeriod = (value: string) => {
  const base = validPeriod(value) ? value : currentPeriod();
  const [year, month] = base.split('-').map(Number);
  return `${year - 1}-${pad(month)}`;
};
const periodParts = (value: string) => {
  const base = validPeriod(value) ? value : currentPeriod();
  const [year, month] = base.split('-').map(Number);
  return { year, month };
};

const fromDateText = (value: string) => {
  const [year, month, day] = value.split('-').map(Number);
  return new Date(year, month - 1, day);
};

/**
 * Focus goes back to the text field when the picker closes from inside it
 * (a pick or Escape), and stays where the person clicked when they click away.
 */
function usePickerFocus(inputRef: RefObject<HTMLInputElement | null>) {
  const clickedAway = useRef(false);
  return {
    onInteractOutside: () => { clickedAway.current = true; },
    onCloseAutoFocus: (event: Event) => {
      event.preventDefault();
      if (!clickedAway.current) inputRef.current?.focus();
      clickedAway.current = false;
    },
  };
}

export function AccountingPeriodInput({ label, value, onChange, placeholder = 'YYYY-MM', help, disabled, ariaLabel, shortcutBaseValue, shortcutBaseLabel }: {
  label: string; value: string; onChange(value: string): void; placeholder?: string; help?: string; disabled?: boolean; ariaLabel?: string;
  shortcutBaseValue?: string; shortcutBaseLabel?: string;
}) {
  const id = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState(value);
  const [open, setOpen] = useState(false);
  const [{ year, month: activeMonth }, setCursor] = useState(periodParts(value));
  const pickerFocus = usePickerFocus(inputRef);
  useEffect(() => setDraft(value), [value]);
  useEffect(() => { if (open) setCursor(periodParts(draft || value)); }, [open, draft, value]);
  const baseShortcut = shortcutBaseValue && validPeriod(shortcutBaseValue) ? shortcutBaseValue : draft || value;
  const error = draft && !validPeriod(draft) ? '请输入 YYYY-MM 会计期间。' : '';
  const commit = (next = draft) => {
    if (!next || validPeriod(next)) onChange(next);
  };
  const shortcut = (next: string) => {
    setDraft(next);
    onChange(next);
  };
  const chooseMonth = (month: number) => {
    shortcut(`${year}-${pad(month)}`);
    setOpen(false);
  };
  const moveActiveMonth = (delta: number) => setCursor((value) => {
    const date = new Date(value.year, value.month - 1 + delta, 1);
    return { year: date.getFullYear(), month: date.getMonth() + 1 };
  });
  return <FieldShell label={label} htmlFor={id} help={help} error={error}>
    <Popover open={open} onOpenChange={setOpen}>
      <div className="fnd-date-picker">
        <div className="fnd-period-field">
          <PopoverAnchor asChild><div className="fnd-period-field__input"><Input ref={inputRef} id={id} aria-label={ariaLabel ?? label} aria-describedby={fieldDescribedBy(id, help, error)} aria-invalid={error ? true : undefined} value={draft} placeholder={placeholder}
            inputMode="numeric" disabled={disabled} onChange={(event) => {
              const next = event.target.value;
              setDraft(next);
              if (!next || validPeriod(next)) onChange(next);
            }} onBlur={() => commit()} onKeyDown={(event) => {
              if (event.key === 'Enter') { event.preventDefault(); commit(); }
              if (event.key === 'Escape') { setDraft(value); setOpen(false); }
              if (event.key === 'ArrowDown' && !disabled) { event.preventDefault(); setOpen(true); }
            }} />
            <PopoverTrigger asChild><button type="button" className="fnd-control-icon fnd-control-icon--calendar" disabled={disabled} aria-label={`${label}打开年月选择`}><CalendarDays size={14} aria-hidden /></button></PopoverTrigger></div></PopoverAnchor>
          <div className="fnd-period-shortcuts">
            <Button type="button" variant="outline" size="chip" disabled={disabled} onClick={() => shortcut(previousPeriod(baseShortcut))} aria-pressed={value === previousPeriod(baseShortcut)} aria-label={`${label}设为${shortcutBaseLabel ? `${shortcutBaseLabel}上期` : '上期'}`}>上期</Button>
            <Button type="button" variant="outline" size="chip" disabled={disabled} onClick={() => shortcut(lastYearPeriod(baseShortcut))} aria-pressed={value === lastYearPeriod(baseShortcut)} aria-label={`${label}设为${shortcutBaseLabel ? `${shortcutBaseLabel}上年同期` : '上年同期'}`}>上年同期</Button>
            <Button type="button" variant="outline" size="chip" disabled={disabled} onClick={() => shortcut(currentPeriod())} aria-pressed={value === currentPeriod()} aria-label={`${label}设为本期`}>本期</Button>
          </div>
        </div>
      </div>
      {/* shadcn has no month view: the month grid stays ours, inside the shared Popover. */}
      <PopoverContent ref={popoverRef} className="fnd-date-picker__popover" aria-label={`${label}年月选择`} tabIndex={-1} {...pickerFocus}
        onOpenAutoFocus={(event) => { event.preventDefault(); popoverRef.current?.focus(); }} onKeyDown={(event) => {
          if (event.key === 'ArrowLeft') { event.preventDefault(); moveActiveMonth(-1); }
          if (event.key === 'ArrowRight') { event.preventDefault(); moveActiveMonth(1); }
          if (event.key === 'ArrowUp') { event.preventDefault(); moveActiveMonth(-4); }
          if (event.key === 'ArrowDown') { event.preventDefault(); moveActiveMonth(4); }
          if (event.key === 'Enter' && event.target === event.currentTarget) { event.preventDefault(); chooseMonth(activeMonth); }
        }}>
        <div className="fnd-date-picker__head">
          <button type="button" onClick={() => setCursor((value) => ({ ...value, year: value.year - 1 }))} aria-label="上一年"><ChevronLeft size={16} aria-hidden /></button>
          <strong>{year} 年</strong>
          <button type="button" onClick={() => setCursor((value) => ({ ...value, year: value.year + 1 }))} aria-label="下一年"><ChevronRight size={16} aria-hidden /></button>
        </div>
        <div className="fnd-month-grid">
          {Array.from({ length: 12 }, (_, index) => index + 1).map((month) => {
            const period = `${year}-${pad(month)}`;
            return <button type="button" key={month} aria-pressed={period === value} data-active={month === activeMonth ? 'true' : undefined} onClick={() => chooseMonth(month)}>{month}月</button>;
          })}
        </div>
      </PopoverContent>
    </Popover>
  </FieldShell>;
}

export function DateInput({ label, value, onChange, placeholder = 'YYYY-MM-DD', help, disabled, ariaLabel }: {
  label: string; value: string; onChange(value: string): void; placeholder?: string; help?: string; disabled?: boolean; ariaLabel?: string;
}) {
  const id = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [draft, setDraft] = useState(value);
  const [open, setOpen] = useState(false);
  const pickerFocus = usePickerFocus(inputRef);
  useEffect(() => setDraft(value), [value]);
  const error = draft && !validDate(draft) ? '请输入有效日期 YYYY-MM-DD。' : '';
  const commit = (next = draft) => {
    if (!next || validDate(next)) onChange(next);
  };
  const selected = validDate(value) ? fromDateText(value) : undefined;
  const shownMonth = validDate(draft) ? fromDateText(draft) : selected;
  const pick = (date: Date) => {
    const next = toDateText(date);
    setDraft(next);
    onChange(next);
    setOpen(false);
  };
  return <FieldShell label={label} htmlFor={id} help={help ?? '支持未来日期，预算和资金预测会用到。'} error={error}>
    <Popover open={open} onOpenChange={setOpen}>
      <div className="fnd-date-picker">
        <PopoverAnchor asChild><div className="fnd-date-field">
          <CalendarDays size={14} aria-hidden />
          <Input ref={inputRef} id={id} aria-label={ariaLabel ?? label} aria-describedby={fieldDescribedBy(id, help ?? '支持未来日期，预算和资金预测会用到。', error)} aria-invalid={error ? true : undefined} value={draft} placeholder={placeholder}
            inputMode="numeric" disabled={disabled} onChange={(event) => {
              const next = event.target.value;
              setDraft(next);
              if (!next || validDate(next)) onChange(next);
            }} onBlur={() => commit()} onKeyDown={(event) => {
              if (event.key === 'Enter') { event.preventDefault(); commit(); }
              if (event.key === 'Escape') { setDraft(value); setOpen(false); }
              if (event.key === 'ArrowDown' && !disabled) { event.preventDefault(); setOpen(true); }
            }} />
          <PopoverTrigger asChild><button type="button" className="fnd-date-field__toggle" disabled={disabled} aria-label={`${label}打开日期选择`}><ChevronDown size={14} aria-hidden /></button></PopoverTrigger>
        </div></PopoverAnchor>
      </div>
      {/* The calendar moves focus to the chosen (or today's) day itself; arrows, PageUp/PageDown and Enter are its own. */}
      <PopoverContent className="fnd-date-picker__popover" aria-label={`${label}日期选择`} {...pickerFocus} onOpenAutoFocus={(event) => event.preventDefault()}>
        <Calendar mode="single" required selected={selected} defaultMonth={shownMonth} autoFocus onSelect={pick} />
        <div className="fnd-calendar__footer">
          <Button type="button" variant="ghost" size="sm" onClick={() => pick(new Date())}>今天</Button>
        </div>
      </PopoverContent>
    </Popover>
  </FieldShell>;
}

export function PeriodRangeInput({ label, start, end, onChange, help, disabled }: {
  label: string; start: string; end: string; onChange(value: { start: string; end: string }): void; help?: string; disabled?: boolean;
}) {
  const error = start && end && validPeriod(start) && validPeriod(end) && start > end ? '开始期间不能晚于结束期间。' : '';
  return <FieldShell label={label} help={help ?? '期间范围按 YYYY-MM 保存。'} error={error}>
    <div className="fnd-range-field">
      <AccountingPeriodInput label={`${label}开始`} ariaLabel={`${label}开始`} value={start} disabled={disabled} onChange={(next) => onChange({ start: next, end })} help=" " />
      <AccountingPeriodInput label={`${label}结束`} ariaLabel={`${label}结束`} value={end} disabled={disabled} onChange={(next) => onChange({ start, end: next })} help=" " />
    </div>
  </FieldShell>;
}

const decimalLike = /^[-+]?((\d{1,3}(,\d{3})+)|\d+)?(\.\d*)?$/;
const formatDecimalText = (value: string) => {
  const clean = value.replaceAll(',', '');
  if (!clean || clean === '-' || clean === '+' || clean.endsWith('.')) return value;
  const [int, fraction] = clean.split('.');
  const sign = int.startsWith('-') || int.startsWith('+') ? int.slice(0, 1) : '';
  const digits = sign ? int.slice(1) : int;
  const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `${sign}${grouped}${fraction == null ? '' : `.${fraction}`}`;
};

export function DecimalInput({ label, value, onChange, placeholder, unit, help, disabled, ariaLabel }: {
  label: string; value: string; onChange(value: string): void; placeholder?: string; unit?: string; help?: string; disabled?: boolean; ariaLabel?: string;
}) {
  const id = useId();
  const [draft, setDraft] = useState(value);
  const [editing, setEditing] = useState(false);
  useEffect(() => { if (!editing) setDraft(value); }, [value, editing]);
  const plain = draft.replaceAll(',', '');
  const error = draft && !decimalLike.test(draft) ? '请输入金额数字，空值与 0 会分开保存。' : '';
  return <FieldShell label={label} htmlFor={id} help={help} error={error}>
    <div className="fnd-decimal-field">
      <Input id={id} aria-label={ariaLabel ?? label} aria-describedby={fieldDescribedBy(id, help, error)} aria-invalid={error ? true : undefined} value={editing ? draft : formatDecimalText(draft)}
        placeholder={placeholder} inputMode="decimal" disabled={disabled} onFocus={() => { setEditing(true); setDraft(value); }}
        onChange={(event) => {
          const next = event.target.value;
          setDraft(next);
          if (!next || decimalLike.test(next)) onChange(next.replaceAll(',', ''));
        }}
        onBlur={() => { setEditing(false); if (!error) setDraft(plain); }}
        onKeyDown={(event) => { if (event.key === 'Escape') { setDraft(value); setEditing(false); } }} />
      {unit ? <span className="fnd-decimal-field__unit">{unit}</span> : null}
    </div>
  </FieldShell>;
}

type SelectBaseProps = {
  label: string;
  options: SelectOption[];
  placeholder?: string;
  emptyLabel?: string;
  disabled?: boolean;
  help?: string;
  allowEmptyLabel?: string;
  ariaLabel?: string;
  clearable?: boolean;
  loading?: boolean;
  loadError?: string;
  unconfigured?: boolean;
  unconfiguredLabel?: string;
  maxOptions?: number;
  truncatedLabel?: string;
};

type FilteredOptions = { options: SelectOption[]; total: number; truncated: boolean };
type SelectFeedback = { kind: 'loading' | 'error' | 'unconfigured'; message: string } | null;

function useSelectPopover(triggerRef: RefObject<HTMLButtonElement | null>) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const change = (next: boolean) => { setOpen(next); if (!next) setQuery(''); };
  const triggerKeys = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') { event.preventDefault(); change(true); }
    if (event.key === 'Escape') { event.preventDefault(); change(false); triggerRef.current?.focus(); }
  };
  return { open, query, setQuery, change, triggerKeys };
}

export function SearchableSelect({ label, value, options, onChange, placeholder = '搜索名称或编码', emptyLabel = '无匹配结果', disabled, help, allowEmptyLabel, ariaLabel, clearable, loading, loadError, unconfigured, unconfiguredLabel, maxOptions = 80, truncatedLabel, compact = false, triggerText }: SelectBaseProps & {
  value: string; onChange(value: string): void; compact?: boolean; triggerText?: string;
}) {
  const id = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const { open, query, setQuery, change, triggerKeys } = useSelectPopover(triggerRef);
  const selected = options.find((option) => option.value === value);
  const invalid = Boolean(value && !selected);
  const filtered = useMemo(() => filterOptions(options, query, allowEmptyLabel, maxOptions), [allowEmptyLabel, maxOptions, options, query]);
  const pick = (option: SelectOption) => {
    if (option.disabled) return;
    onChange(option.value);
    change(false);
  };
  const feedback = selectFeedback(loading, loadError, unconfigured, unconfiguredLabel);
  const visibleLabel = selected ? [selected.label, selected.meta].filter(Boolean).join(' · ') : invalid ? `已失效：${value}` : allowEmptyLabel && !value ? allowEmptyLabel : '';
  return <FieldShell label={label} htmlFor={id} help={help} hideLabel={compact}
    error={invalid ? `当前选择已失效：${value}。请清空或重新选择。` : undefined}>
    <Popover open={open} onOpenChange={change}>
      <div className={`fnd-combobox${compact ? ' fnd-combobox--compact' : ''}`}>
        <PopoverTrigger asChild><button ref={triggerRef} id={id} type="button" className="fnd-combobox__button" title={compact ? visibleLabel : undefined} aria-label={ariaLabel ?? label} aria-describedby={fieldDescribedBy(id, help, invalid && `当前选择已失效：${value}。请清空或重新选择。`)} aria-invalid={invalid || undefined}
          aria-haspopup="listbox" disabled={disabled} onKeyDown={triggerKeys}>
          {compact && <span className="fnd-combobox__prefix">{label}</span>}
          <span>{invalid ? visibleLabel : triggerText ?? (visibleLabel || placeholder)}</span><ChevronDown size={14} aria-hidden />
        </button></PopoverTrigger>
        {(value && (clearable || allowEmptyLabel || invalid)) ? <button type="button" className="fnd-combobox__clear" aria-label={`清空${label}`} disabled={disabled}
          onClick={() => onChange('')}><X size={13} aria-hidden /></button> : null}
      </div>
      <SelectPopover compact={compact} label={label} query={query} setQuery={setQuery} result={filtered} value={value} feedback={feedback} emptyLabel={emptyLabel}
        placeholder={placeholder} truncatedLabel={truncatedLabel} onPick={pick} />
    </Popover>
  </FieldShell>;
}

export function MultiSelect({ label, values, options, onChange, placeholder = '搜索名称或编码', emptyLabel = '无匹配结果', disabled, help, ariaLabel, loading, loadError, unconfigured, unconfiguredLabel, maxOptions = 80, truncatedLabel }: SelectBaseProps & {
  values: string[]; onChange(values: string[]): void;
}) {
  const id = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const { open, query, setQuery, change, triggerKeys } = useSelectPopover(triggerRef);
  const selected = options.filter((option) => values.includes(option.value));
  const missing = values.filter((value) => !options.some((option) => option.value === value));
  const filtered = useMemo(() => filterOptions(options, query, undefined, maxOptions), [maxOptions, options, query]);
  const toggle = (option: SelectOption) => {
    if (option.disabled) return;
    onChange(values.includes(option.value) ? values.filter((value) => value !== option.value) : [...values, option.value]);
  };
  const feedback = selectFeedback(loading, loadError, unconfigured, unconfiguredLabel);
  const visibleLabel = selected.length || missing.length ? [...selected.map((option) => option.label), ...missing.map((value) => `已失效：${value}`)].join('、') : placeholder;
  return <FieldShell label={label} htmlFor={id} help={help}
    error={missing.length ? `部分已选项已失效：${missing.join('、')}。请移除后继续。` : undefined}>
    <Popover open={open} onOpenChange={change}>
      <div className="fnd-combobox">
        <PopoverTrigger asChild><button ref={triggerRef} id={id} type="button" className="fnd-combobox__button" aria-label={ariaLabel ?? label} aria-describedby={fieldDescribedBy(id, help, missing.length ? `部分已选项已失效：${missing.join('、')}。请移除后继续。` : undefined)} aria-invalid={missing.length ? true : undefined}
          aria-haspopup="listbox" disabled={disabled} onKeyDown={triggerKeys}>
          <span>{visibleLabel}</span><ChevronDown size={14} aria-hidden />
        </button></PopoverTrigger>
        {values.length ? <button type="button" className="fnd-combobox__clear" aria-label={`清空${label}`} disabled={disabled}
          onClick={() => onChange([])}><X size={13} aria-hidden /></button> : null}
        {missing.length ? <button type="button" className="fnd-combobox__repair" aria-label={`移除${label}失效项`} disabled={disabled}
          onClick={() => onChange(values.filter((value) => options.some((option) => option.value === value)))}>移除失效项</button> : null}
      </div>
      <SelectPopover label={label} query={query} setQuery={setQuery} result={filtered} value={values} multi feedback={feedback} emptyLabel={emptyLabel}
        placeholder={placeholder} truncatedLabel={truncatedLabel} onPick={toggle} />
    </Popover>
  </FieldShell>;
}

function filterOptions(options: SelectOption[], query: string, allowEmptyLabel?: string, maxOptions = 80): FilteredOptions {
  const needle = searchKey(query);
  const base = allowEmptyLabel ? [{ value: '', label: allowEmptyLabel }, ...options] : options;
  const score = (option: SelectOption) => {
    const label = searchKey(option.label);
    const value = searchKey(option.value);
    const meta = searchKey(`${option.meta ?? ''} ${option.keywords ?? ''}`);
    if (!needle) return 0;
    if (label.includes(needle)) return 0;
    if (value.includes(needle)) return 1;
    if (meta.includes(needle)) return 2;
    return 3;
  };
  const matched = needle ? base
    .map((option, index) => ({ option, index, score: score(option) }))
    .filter((item) => item.score < 3)
    .sort((a, b) => a.score - b.score || a.index - b.index)
    .map((item) => item.option) : base;
  const shown = matched.slice(0, maxOptions);
  return { options: shown, total: matched.length, truncated: matched.length > shown.length };
}

function selectFeedback(loading?: boolean, loadError?: string, unconfigured?: boolean, unconfiguredLabel?: string): SelectFeedback {
  if (loading) return { kind: 'loading', message: '正在读取选项…' };
  if (loadError) return { kind: 'error', message: `选项读取失败：${loadError}` };
  if (unconfigured) return { kind: 'unconfigured', message: unconfiguredLabel ?? '请先完成前置设置。' };
  return null;
}

/**
 * cmdk highlights the first option on open but only names it in the input's
 * aria-activedescendant after the first arrow key. Keep the input pointed at
 * the highlighted option so a screen reader hears where Enter lands.
 */
function useActiveOptionAnnounced(root: HTMLElement | null) {
  useEffect(() => {
    if (!root) return undefined;
    const sync = () => {
      const input = root.querySelector('[cmdk-input]');
      const active = root.querySelector('[cmdk-item][aria-selected="true"]');
      if (!input) return;
      if (!active) input.removeAttribute('aria-activedescendant');
      else if (input.getAttribute('aria-activedescendant') !== active.id) input.setAttribute('aria-activedescendant', active.id);
    };
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(root, { subtree: true, childList: true, attributes: true, attributeFilter: ['aria-selected', 'aria-activedescendant'] });
    return () => observer.disconnect();
  }, [root]);
}

/**
 * shadcn Combobox: Popover + Command (cmdk). Filtering stays ours (label, then
 * code, then meta; capped list), so cmdk only keeps the active option, arrow
 * keys, Enter and aria-activedescendant. Enter waits for IME composition.
 * cmdk's aria-selected marks the highlighted row, so multi-select options carry
 * their chosen state in aria-checked instead.
 */
function SelectPopover({ label, query, setQuery, result, value, multi, compact, feedback, emptyLabel, placeholder, truncatedLabel, onPick }: {
  label: string; query: string; setQuery(value: string): void; result: FilteredOptions; value: string | string[];
  multi?: boolean; compact?: boolean; feedback: SelectFeedback; emptyLabel?: string; placeholder?: string; truncatedLabel?: string;
  onPick(option: SelectOption): void;
}) {
  const composing = useRef(false);
  const [commandRoot, setCommandRoot] = useState<HTMLDivElement | null>(null);
  useActiveOptionAnnounced(commandRoot);
  const chosen = (option: SelectOption) => Array.isArray(value) ? value.includes(option.value) : option.value === value;
  const options = result.options;
  return <PopoverContent className={`fnd-combobox__popover${compact ? ' fnd-combobox__popover--compact' : ''}`} aria-label={label}>
    <Command ref={setCommandRoot} shouldFilter={false} label={`${label}搜索`} onKeyDown={(event) => {
      if (event.key === 'Enter' && composing.current) event.preventDefault();
    }}>
      <CommandInput aria-label={`${label}搜索`} value={query} onValueChange={setQuery} placeholder={placeholder ?? '搜索名称或编码'}
        onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }} />
      {feedback ? <p className="fnd-combobox__state" data-state={feedback.kind} role={feedback.kind === 'error' ? 'alert' : 'status'}>{feedback.message}</p>
        : options.length ? <>
          <CommandList label={label}>
            {options.map((option, index) => <CommandItem key={`${option.value}:${index}`} value={String(index)} disabled={option.disabled}
              data-checked={chosen(option) ? 'true' : undefined} aria-checked={multi ? chosen(option) : undefined} onSelect={() => onPick(option)}>
              <span>{option.label}</span>{option.meta ? <small>{option.meta}</small> : null}{chosen(option) ? <Check size={14} aria-label="已选" /> : null}
            </CommandItem>)}
          </CommandList>
          {result.truncated ? <p className="fnd-combobox__truncated" role="status">{truncatedLabel ?? `已显示前 ${options.length} 项，共 ${result.total} 项；继续输入名称或编码可访问其余项。`}</p> : null}
        </> : <p className="fnd-combobox__empty">{emptyLabel ?? '无匹配结果'}</p>}
    </Command>
  </PopoverContent>;
}
