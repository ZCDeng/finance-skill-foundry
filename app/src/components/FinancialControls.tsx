import { useEffect, useId, useMemo, useRef, useState, type CSSProperties, type MutableRefObject, type ReactNode, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import { CalendarDays, Check, ChevronDown, Search, X } from 'lucide-react';
import { Field, FieldDescription, FieldError, FieldLabel, FieldTitle } from './ui/field.js';
import { Input } from './ui/input.js';
import './financial-controls.css';

export type SelectOption = {
  value: string;
  label: string;
  meta?: string;
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
const dateParts = (value: string) => {
  const base = validDate(value) ? value : toDateText(new Date());
  const [year, month, day] = base.split('-').map(Number);
  return { year, month, day };
};
const daysInMonth = (year: number, month: number) => new Date(year, month, 0).getDate();

type FloatingPosition = { top: number; left: number; width: number; maxHeight: number; placement: 'top' | 'bottom'; align: 'start' | 'end' };

function useFixedPopover(open: boolean, anchor: RefObject<HTMLElement | null>, maxWidth: number, estimatedHeight: number, minWidth = 220): FloatingPosition | null {
  const [position, setPosition] = useState<FloatingPosition | null>(null);
  useEffect(() => {
    if (!open) { setPosition(null); return undefined; }
    const margin = 12;
    const gap = 6;
    const update = () => {
      const rect = anchor.current?.getBoundingClientRect();
      if (!rect) return;
      const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 1024;
      const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 768;
      const boundedMax = Math.max(220, Math.min(maxWidth, viewportWidth - margin * 2));
      const width = Math.max(Math.min(rect.width || boundedMax, boundedMax), Math.min(minWidth, boundedMax));
      const spaceBelow = viewportHeight - rect.bottom - margin;
      const spaceAbove = rect.top - margin;
      const placement = spaceBelow < estimatedHeight && spaceAbove > spaceBelow ? 'top' : 'bottom';
      const align = rect.left + width > viewportWidth - margin && rect.right - width >= margin ? 'end' : 'start';
      const rawLeft = align === 'end' ? rect.right - width : rect.left;
      const left = Math.min(Math.max(rawLeft, margin), viewportWidth - margin - width);
      const top = placement === 'top' ? rect.top - gap : rect.bottom + gap;
      const maxHeight = Math.max(0, (placement === 'top' ? spaceAbove : spaceBelow) - gap);
      setPosition({ top, left, width, maxHeight, placement, align });
    };
    update();
    const frame = window.requestAnimationFrame(update);
    window.addEventListener('resize', update);
    window.addEventListener('scroll', update, true);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener('resize', update);
      window.removeEventListener('scroll', update, true);
    };
  }, [anchor, estimatedHeight, maxWidth, minWidth, open]);
  return position;
}

const popoverStyle = (position: FloatingPosition | null): CSSProperties | undefined => position
  ? { top: position.top, left: position.left, width: position.width, maxHeight: position.maxHeight,
    overflowY: 'auto', transform: position.placement === 'top' ? 'translateY(-100%)' : undefined }
  : undefined;

function useOutsideClose(open: boolean, root: RefObject<HTMLElement | null>, close: () => void, floating?: RefObject<HTMLElement | null>) {
  useEffect(() => {
    if (!open) return undefined;
    const listener = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!root.current?.contains(target) && !floating?.current?.contains(target)) close();
    };
    document.addEventListener('mousedown', listener);
    return () => document.removeEventListener('mousedown', listener);
  }, [open, root, close, floating]);
}

const floatingPortal = (node: ReactNode) => createPortal(node, document.body);

export function AccountingPeriodInput({ label, value, onChange, placeholder = 'YYYY-MM', help, disabled, ariaLabel, shortcutBaseValue, shortcutBaseLabel }: {
  label: string; value: string; onChange(value: string): void; placeholder?: string; help?: string; disabled?: boolean; ariaLabel?: string;
  shortcutBaseValue?: string; shortcutBaseLabel?: string;
}) {
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState(value);
  const [open, setOpen] = useState(false);
  const [{ year, month: activeMonth }, setCursor] = useState(periodParts(value));
  const popoverPosition = useFixedPopover(open, inputRef, 320, 260);
  useEffect(() => setDraft(value), [value]);
  useEffect(() => { if (open) setCursor(periodParts(draft || value)); }, [open, draft, value]);
  useEffect(() => { if (open) popoverRef.current?.focus(); }, [open]);
  useOutsideClose(open, root, () => setOpen(false), popoverRef);
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
    const next = `${year}-${pad(month)}`;
    shortcut(next);
    setOpen(false);
    inputRef.current?.focus();
  };
  const moveActiveMonth = (delta: number) => setCursor((value) => {
    const date = new Date(value.year, value.month - 1 + delta, 1);
    return { year: date.getFullYear(), month: date.getMonth() + 1 };
  });
  return <FieldShell label={label} htmlFor={id} help={help ?? '会计期间不会转换成某一天。'} error={error}>
    <div className="fnd-date-picker" ref={root}>
      <div className="fnd-period-field">
        <div className="fnd-period-field__input"><Input ref={inputRef} id={id} aria-label={ariaLabel ?? label} aria-describedby={fieldDescribedBy(id, help ?? '会计期间不会转换成某一天。', error)} aria-invalid={error ? true : undefined} value={draft} placeholder={placeholder}
          inputMode="numeric" disabled={disabled} onChange={(event) => {
            const next = event.target.value;
            setDraft(next);
            if (!next || validPeriod(next)) onChange(next);
          }} onBlur={() => commit()} onKeyDown={(event) => {
            if (event.key === 'Enter') { event.preventDefault(); commit(); }
            if (event.key === 'Escape') { setDraft(value); setOpen(false); }
            if (event.key === 'ArrowDown' && !disabled) { event.preventDefault(); setOpen(true); }
          }} />
          <button type="button" className="fnd-control-icon fnd-control-icon--calendar" disabled={disabled} onClick={() => setOpen((current) => !current)} aria-label={`${label}打开年月选择`}><CalendarDays size={14} aria-hidden /></button></div>
        <div className="fnd-period-shortcuts">
          <button type="button" className="fnd-control-icon" disabled={disabled} onClick={() => shortcut(previousPeriod(baseShortcut))} aria-pressed={value === previousPeriod(baseShortcut)} aria-label={`${label}设为${shortcutBaseLabel ? `${shortcutBaseLabel}上期` : '上期'}`}>上期</button>
          <button type="button" className="fnd-control-icon" disabled={disabled} onClick={() => shortcut(lastYearPeriod(baseShortcut))} aria-pressed={value === lastYearPeriod(baseShortcut)} aria-label={`${label}设为${shortcutBaseLabel ? `${shortcutBaseLabel}上年同期` : '上年同期'}`}>上年同期</button>
          <button type="button" className="fnd-control-icon" disabled={disabled} onClick={() => shortcut(currentPeriod())} aria-pressed={value === currentPeriod()} aria-label={`${label}设为本期`}>本期</button>
        </div>
      </div>
      {open ? floatingPortal(<div ref={popoverRef} className="fnd-date-picker__popover" role="dialog" aria-label={`${label}年月选择`} tabIndex={-1}
        style={popoverStyle(popoverPosition)} data-placement={popoverPosition?.placement} data-align={popoverPosition?.align} onKeyDown={(event) => {
        if (event.key === 'Escape') { event.preventDefault(); setOpen(false); inputRef.current?.focus(); }
        if (event.key === 'ArrowLeft') { event.preventDefault(); moveActiveMonth(-1); }
        if (event.key === 'ArrowRight') { event.preventDefault(); moveActiveMonth(1); }
        if (event.key === 'ArrowUp') { event.preventDefault(); moveActiveMonth(-4); }
        if (event.key === 'ArrowDown') { event.preventDefault(); moveActiveMonth(4); }
        if (event.key === 'Enter') { event.preventDefault(); chooseMonth(activeMonth); }
      }}>
        <div className="fnd-date-picker__head">
          <button type="button" onClick={() => setCursor((value) => ({ ...value, year: value.year - 1 }))} aria-label="上一年">‹</button>
          <strong>{year} 年</strong>
          <button type="button" onClick={() => setCursor((value) => ({ ...value, year: value.year + 1 }))} aria-label="下一年">›</button>
        </div>
        <div className="fnd-month-grid">
          {Array.from({ length: 12 }, (_, index) => index + 1).map((month) => {
            const period = `${year}-${pad(month)}`;
            return <button type="button" key={month} aria-pressed={period === value} data-active={month === activeMonth ? 'true' : undefined} onClick={() => chooseMonth(month)}>{month}月</button>;
          })}
        </div>
      </div>) : null}
    </div>
  </FieldShell>;
}

export function DateInput({ label, value, onChange, placeholder = 'YYYY-MM-DD', help, disabled, ariaLabel }: {
  label: string; value: string; onChange(value: string): void; placeholder?: string; help?: string; disabled?: boolean; ariaLabel?: string;
}) {
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState(value);
  const [open, setOpen] = useState(false);
  const [{ year, month, day: activeDay }, setCursor] = useState(dateParts(value));
  const popoverPosition = useFixedPopover(open, inputRef, 320, 340);
  useEffect(() => setDraft(value), [value]);
  useEffect(() => { if (open) setCursor(dateParts(draft || value)); }, [open, draft, value]);
  useEffect(() => { if (open) popoverRef.current?.focus(); }, [open]);
  useOutsideClose(open, root, () => setOpen(false), popoverRef);
  const error = draft && !validDate(draft) ? '请输入有效日期 YYYY-MM-DD。' : '';
  const commit = (next = draft) => {
    if (!next || validDate(next)) onChange(next);
  };
  const chooseDay = (day: number) => {
    const next = `${year}-${pad(month)}-${pad(day)}`;
    setDraft(next);
    onChange(next);
    setOpen(false);
    inputRef.current?.focus();
  };
  const moveDay = (delta: number) => setCursor((value) => {
    const date = new Date(value.year, value.month - 1, value.day + delta);
    return { year: date.getFullYear(), month: date.getMonth() + 1, day: date.getDate() };
  });
  const moveMonth = (delta: number) => setCursor((value) => {
    const date = new Date(value.year, value.month - 1 + delta, 1);
    return { year: date.getFullYear(), month: date.getMonth() + 1, day: Math.min(value.day, daysInMonth(date.getFullYear(), date.getMonth() + 1)) };
  });
  return <FieldShell label={label} htmlFor={id} help={help ?? '支持未来日期，预算和资金预测会用到。'} error={error}>
    <div className="fnd-date-picker" ref={root}>
      <div className="fnd-date-field">
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
        <button type="button" className="fnd-date-field__toggle" disabled={disabled} onClick={() => setOpen((current) => !current)} aria-label={`${label}打开日期选择`}><ChevronDown size={14} aria-hidden /></button>
      </div>
      {open ? floatingPortal(<div ref={popoverRef} className="fnd-date-picker__popover" role="dialog" aria-label={`${label}日期选择`} tabIndex={-1}
        style={popoverStyle(popoverPosition)} data-placement={popoverPosition?.placement} data-align={popoverPosition?.align} onKeyDown={(event) => {
        if (event.key === 'Escape') { event.preventDefault(); setOpen(false); inputRef.current?.focus(); }
        if (event.key === 'ArrowLeft') { event.preventDefault(); moveDay(-1); }
        if (event.key === 'ArrowRight') { event.preventDefault(); moveDay(1); }
        if (event.key === 'ArrowUp') { event.preventDefault(); moveDay(-7); }
        if (event.key === 'ArrowDown') { event.preventDefault(); moveDay(7); }
        if (event.key === 'PageUp') { event.preventDefault(); moveMonth(-1); }
        if (event.key === 'PageDown') { event.preventDefault(); moveMonth(1); }
        if (event.key === 'Enter') { event.preventDefault(); chooseDay(activeDay); }
      }}>
        <div className="fnd-date-picker__head">
          <button type="button" onClick={() => moveMonth(-1)} aria-label="上一月">‹</button>
          <strong>{year} 年 {month} 月</strong>
          <button type="button" onClick={() => moveMonth(1)} aria-label="下一月">›</button>
        </div>
        <div className="fnd-week-grid" aria-hidden>{['一', '二', '三', '四', '五', '六', '日'].map((day) => <span key={day}>{day}</span>)}</div>
        <div className="fnd-day-grid">
          {Array.from({ length: (new Date(year, month - 1, 1).getDay() + 6) % 7 }, (_, index) => <span key={`blank-${index}`} />)}
          {Array.from({ length: daysInMonth(year, month) }, (_, index) => index + 1).map((day) => {
            const date = `${year}-${pad(month)}-${pad(day)}`;
            return <button type="button" key={day} aria-pressed={date === value} data-active={day === activeDay ? 'true' : undefined} onClick={() => chooseDay(day)}>{day}</button>;
          })}
        </div>
      </div>) : null}
    </div>
  </FieldShell>;
}

export function DateRangeInput({ label, start, end, onChange, help, disabled }: {
  label: string; start: string; end: string; onChange(value: { start: string; end: string }): void; help?: string; disabled?: boolean;
}) {
  const error = start && end && validDate(start) && validDate(end) && start > end ? '开始日期不能晚于结束日期。' : '';
  return <FieldShell label={label} help={help ?? '日期范围按 YYYY-MM-DD 保存。'} error={error}>
    <div className="fnd-range-field">
      <DateInput label={`${label}开始`} ariaLabel={`${label}开始`} value={start} disabled={disabled} onChange={(next) => onChange({ start: next, end })} help=" " />
      <DateInput label={`${label}结束`} ariaLabel={`${label}结束`} value={end} disabled={disabled} onChange={(next) => onChange({ start, end: next })} help=" " />
    </div>
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

export function SearchableSelect({ label, value, options, onChange, placeholder = '搜索名称或编码', emptyLabel = '无匹配结果', disabled, help, allowEmptyLabel, ariaLabel, clearable, loading, loadError, unconfigured, unconfiguredLabel, maxOptions = 80, truncatedLabel, compact = false, triggerText }: SelectBaseProps & {
  value: string; onChange(value: string): void; compact?: boolean; triggerText?: string;
}) {
  const id = useId();
  const listId = `${id}-listbox`;
  const root = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const composing = useRef(false);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const selected = options.find((option) => option.value === value);
  const invalid = Boolean(value && !selected);
  const filtered = useMemo(() => filterOptions(options, query, allowEmptyLabel, maxOptions), [allowEmptyLabel, maxOptions, options, query]);
  const popoverPosition = useFixedPopover(open, triggerRef, 420, 360, compact ? 360 : 220);
  const close = (focusTrigger = false) => {
    setOpen(false);
    setQuery('');
    if (focusTrigger) triggerRef.current?.focus();
  };
  useOutsideClose(open, root, () => close(false), popoverRef);
  useEffect(() => setActiveIndex(0), [query, open]);
  const pick = (option: SelectOption) => {
    if (option.disabled) return;
    onChange(option.value);
    close(true);
  };
  const feedback = selectFeedback(loading, loadError, unconfigured, unconfiguredLabel);
  const visibleLabel = selected ? [selected.label, selected.meta].filter(Boolean).join(' · ') : invalid ? `已失效：${value}` : allowEmptyLabel && !value ? allowEmptyLabel : '';
  return <FieldShell label={label} htmlFor={id} help={help} hideLabel={compact}
    error={invalid ? `当前选择已失效：${value}。请清空或重新选择。` : undefined}>
    <div className={`fnd-combobox${compact ? ' fnd-combobox--compact' : ''}`} ref={root}>
      <button ref={triggerRef} id={id} type="button" className="fnd-combobox__button" title={compact ? visibleLabel : undefined} aria-label={ariaLabel ?? label} aria-describedby={fieldDescribedBy(id, help, invalid && `当前选择已失效：${value}。请清空或重新选择。`)} aria-invalid={invalid || undefined}
        aria-haspopup="listbox" aria-expanded={open} aria-controls={listId} disabled={disabled}
        onClick={() => setOpen((current) => !current)} onKeyDown={(event) => {
          if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setOpen(true); }
          if (event.key === 'Escape') { event.preventDefault(); close(true); }
        }}>
        {compact && <span className="fnd-combobox__prefix">{label}</span>}
        <span>{invalid ? visibleLabel : triggerText ?? (visibleLabel || placeholder)}</span><ChevronDown size={14} aria-hidden />
      </button>
      {open && floatingPortal(<SelectPopover popoverRef={popoverRef} label={label} listId={listId} query={query} setQuery={setQuery} result={filtered} value={value}
        activeIndex={activeIndex} setActiveIndex={setActiveIndex} composing={composing} feedback={feedback} emptyLabel={emptyLabel}
        placeholder={placeholder} truncatedLabel={truncatedLabel} popoverPosition={popoverPosition} onPick={pick} onClose={() => close(true)} />)}
      {(value && (clearable || allowEmptyLabel || invalid)) ? <button type="button" className="fnd-combobox__clear" aria-label={`清空${label}`} disabled={disabled}
        onClick={() => onChange('')}><X size={13} aria-hidden /></button> : null}
    </div>
  </FieldShell>;
}

export function MultiSelect({ label, values, options, onChange, placeholder = '搜索名称或编码', emptyLabel = '无匹配结果', disabled, help, ariaLabel, loading, loadError, unconfigured, unconfiguredLabel, maxOptions = 80, truncatedLabel }: SelectBaseProps & {
  values: string[]; onChange(values: string[]): void;
}) {
  const id = useId();
  const listId = `${id}-listbox`;
  const root = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const composing = useRef(false);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const selected = options.filter((option) => values.includes(option.value));
  const missing = values.filter((value) => !options.some((option) => option.value === value));
  const filtered = useMemo(() => filterOptions(options, query, undefined, maxOptions), [maxOptions, options, query]);
  const popoverPosition = useFixedPopover(open, triggerRef, 420, 360);
  const close = (focusTrigger = false) => {
    setOpen(false);
    setQuery('');
    if (focusTrigger) triggerRef.current?.focus();
  };
  useOutsideClose(open, root, () => close(false), popoverRef);
  useEffect(() => setActiveIndex(0), [query, open]);
  const toggle = (option: SelectOption) => {
    if (option.disabled) return;
    onChange(values.includes(option.value) ? values.filter((value) => value !== option.value) : [...values, option.value]);
  };
  const feedback = selectFeedback(loading, loadError, unconfigured, unconfiguredLabel);
  const visibleLabel = selected.length || missing.length ? [...selected.map((option) => option.label), ...missing.map((value) => `已失效：${value}`)].join('、') : placeholder;
  return <FieldShell label={label} htmlFor={id} help={help}
    error={missing.length ? `部分已选项已失效：${missing.join('、')}。请移除后继续。` : undefined}>
    <div className="fnd-combobox" ref={root}>
      <button ref={triggerRef} id={id} type="button" className="fnd-combobox__button" aria-label={ariaLabel ?? label} aria-describedby={fieldDescribedBy(id, help, missing.length ? `部分已选项已失效：${missing.join('、')}。请移除后继续。` : undefined)} aria-invalid={missing.length ? true : undefined}
        aria-haspopup="listbox" aria-expanded={open} aria-controls={listId} disabled={disabled}
        onClick={() => setOpen((current) => !current)} onKeyDown={(event) => {
          if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setOpen(true); }
          if (event.key === 'Escape') { event.preventDefault(); close(true); }
        }}>
        <span>{visibleLabel}</span><ChevronDown size={14} aria-hidden />
      </button>
      {open && floatingPortal(<SelectPopover popoverRef={popoverRef} label={label} listId={listId} query={query} setQuery={setQuery} result={filtered} value={values}
        activeIndex={activeIndex} setActiveIndex={setActiveIndex} composing={composing} multi feedback={feedback} emptyLabel={emptyLabel}
        placeholder={placeholder} truncatedLabel={truncatedLabel} popoverPosition={popoverPosition} onPick={toggle} onClose={() => close(true)} />)}
      {values.length ? <button type="button" className="fnd-combobox__clear" aria-label={`清空${label}`} disabled={disabled}
        onClick={() => onChange([])}><X size={13} aria-hidden /></button> : null}
      {missing.length ? <button type="button" className="fnd-combobox__repair" aria-label={`移除${label}失效项`} disabled={disabled}
        onClick={() => onChange(values.filter((value) => options.some((option) => option.value === value)))}>移除失效项</button> : null}
    </div>
  </FieldShell>;
}

function filterOptions(options: SelectOption[], query: string, allowEmptyLabel?: string, maxOptions = 80): FilteredOptions {
  const needle = query.trim().toLowerCase();
  const base = allowEmptyLabel ? [{ value: '', label: allowEmptyLabel }, ...options] : options;
  const score = (option: SelectOption) => {
    const label = option.label.toLowerCase();
    const value = option.value.toLowerCase();
    const meta = (option.meta ?? '').toLowerCase();
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

function SelectPopover({ popoverRef, label, listId, query, setQuery, result, value, activeIndex, setActiveIndex, composing, multi, feedback, emptyLabel, placeholder, truncatedLabel, popoverPosition, onPick, onClose }: {
  popoverRef: RefObject<HTMLDivElement | null>; label: string; listId: string; query: string; setQuery(value: string): void; result: FilteredOptions; value: string | string[];
  activeIndex: number; setActiveIndex(updater: (index: number) => number): void; composing: MutableRefObject<boolean>; multi?: boolean; feedback: SelectFeedback;
  emptyLabel?: string; placeholder?: string; truncatedLabel?: string; popoverPosition: FloatingPosition | null;
  onPick(option: SelectOption): void; onClose(): void;
}) {
  const selected = (option: SelectOption) => Array.isArray(value) ? value.includes(option.value) : option.value === value;
  const listRef = useRef<HTMLUListElement>(null);
  const options = result.options;
  const activeOption = feedback ? undefined : options[activeIndex];
  const activeOptionId = activeOption ? `${listId}-option-${activeIndex}` : undefined;
  useEffect(() => {
    if (!activeOptionId) return;
    const activeElement = listRef.current?.children.item(activeIndex) as HTMLElement | null;
    activeElement?.scrollIntoView?.({ block: 'nearest' });
  }, [activeIndex, activeOptionId]);
  return <div ref={popoverRef} className="fnd-combobox__popover" style={popoverStyle(popoverPosition)} data-placement={popoverPosition?.placement} data-align={popoverPosition?.align}>
    <div className="fnd-combobox__search"><Search size={14} aria-hidden /><Input aria-label={`${label}搜索`} value={query}
      aria-controls={feedback ? undefined : listId} aria-activedescendant={activeOptionId}
      placeholder={placeholder ?? '搜索名称或编码'} onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }}
      onChange={(event) => setQuery(event.target.value)} autoFocus onKeyDown={(event) => {
        if (!feedback && event.key === 'ArrowDown') { event.preventDefault(); setActiveIndex((index) => Math.min(index + 1, Math.max(0, options.length - 1))); }
        if (!feedback && event.key === 'ArrowUp') { event.preventDefault(); setActiveIndex((index) => Math.max(0, index - 1)); }
        if (event.key === 'Escape') { event.preventDefault(); onClose(); }
        if (!feedback && event.key === 'Enter' && !composing.current && activeOption) { event.preventDefault(); onPick(activeOption); }
      }} /></div>
    {feedback ? <p className="fnd-combobox__state" data-state={feedback.kind} role={feedback.kind === 'error' ? 'alert' : 'status'}>{feedback.message}</p>
      : options.length ? <>
        <ul ref={listRef} id={listId} role="listbox" aria-multiselectable={multi || undefined} className="fnd-combobox__list" aria-label={label}>
          {options.map((option, index) => <li id={`${listId}-option-${index}`} key={`${option.value}:${index}`} role="option" aria-selected={selected(option)}
            data-active={index === activeIndex ? 'true' : undefined} data-disabled={option.disabled ? 'true' : undefined}
            onMouseMove={() => setActiveIndex(() => index)} onMouseDown={(event) => { event.preventDefault(); onPick(option); }}>
            <span>{option.label}</span>{option.meta ? <small>{option.meta}</small> : null}{selected(option) ? <Check size={14} aria-hidden /> : null}
          </li>)}
        </ul>
        {result.truncated ? <p className="fnd-combobox__truncated" role="status">{truncatedLabel ?? `已显示前 ${options.length} 项，共 ${result.total} 项；继续输入名称或编码可访问其余项。`}</p> : null}
      </> : <p className="fnd-combobox__empty">{emptyLabel ?? '无匹配结果'}</p>}
  </div>;
}
