import { useEffect, useRef, type ComponentProps } from 'react';
import { ChevronDownIcon, ChevronLeftIcon, ChevronRightIcon } from 'lucide-react';
import { DayPicker, getDefaultClassNames, type DayButtonProps } from 'react-day-picker';
import { zhCN } from 'react-day-picker/locale';

import { cn } from '@/lib/utils.js';

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六'];

/** How far the year dropdown reaches either side of today, unless the caller sets its own months. */
const YEARS_AROUND = 10;

/*
 * shadcn's Calendar on react-day-picker, set for Chinese finance use: weeks
 * start on Monday, the caption is a year and a month dropdown ("2026 年",
 * "8 月") so an ageing date a year back is two picks, and weekdays are one
 * character. Days are styled in financial-controls.css (.fnd-calendar*).
 */
function Calendar({ className, classNames, formatters, labels, components, captionLayout = 'dropdown', startMonth, endMonth, ...props }: ComponentProps<typeof DayPicker>) {
  const defaults = getDefaultClassNames();
  const thisYear = new Date().getFullYear();
  return (
    <DayPicker
      data-slot="calendar"
      locale={zhCN}
      weekStartsOn={1}
      showOutsideDays={false}
      captionLayout={captionLayout}
      startMonth={startMonth ?? new Date(thisYear - YEARS_AROUND, 0, 1)}
      endMonth={endMonth ?? new Date(thisYear + YEARS_AROUND, 11, 1)}
      className={cn('fnd-calendar', className)}
      formatters={{
        formatCaption: (date) => `${date.getFullYear()} 年 ${date.getMonth() + 1} 月`,
        formatYearDropdown: (date) => `${date.getFullYear()} 年`,
        formatMonthDropdown: (date) => `${date.getMonth() + 1} 月`,
        formatWeekdayName: (date) => WEEKDAYS[date.getDay()],
        ...formatters,
      }}
      labels={{
        labelPrevious: () => '上一月',
        labelNext: () => '下一月',
        labelYearDropdown: () => '选择年份',
        labelMonthDropdown: () => '选择月份',
        labelDayButton: (date, modifiers) => `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日${modifiers.today ? '，今天' : ''}${modifiers.selected ? '，已选' : ''}`,
        labelGrid: (date) => `${date.getFullYear()} 年 ${date.getMonth() + 1} 月`,
        ...labels,
      }}
      classNames={{
        root: cn(defaults.root, 'fnd-calendar__root'),
        months: 'fnd-calendar__months',
        month: 'fnd-calendar__month',
        nav: 'fnd-calendar__nav',
        button_previous: 'fnd-calendar__nav-button',
        button_next: 'fnd-calendar__nav-button',
        month_caption: 'fnd-calendar__caption',
        caption_label: 'fnd-calendar__caption-label',
        dropdowns: 'fnd-calendar__dropdowns',
        dropdown_root: 'fnd-calendar__dropdown-root',
        dropdown: 'fnd-calendar__dropdown',
        month_grid: 'fnd-calendar__grid',
        weekdays: 'fnd-calendar__weekdays',
        weekday: 'fnd-calendar__weekday',
        week: 'fnd-calendar__week',
        day: 'fnd-calendar__day',
        day_button: 'fnd-calendar__day-button',
        selected: 'fnd-calendar__day--selected',
        today: 'fnd-calendar__day--today',
        outside: 'fnd-calendar__day--outside',
        disabled: 'fnd-calendar__day--disabled',
        hidden: 'invisible',
        ...classNames,
      }}
      components={{
        Chevron: ({ orientation, className: chevronClass }) => orientation === 'left'
          ? <ChevronLeftIcon className={chevronClass} size={16} aria-hidden />
          : orientation === 'right'
            ? <ChevronRightIcon className={chevronClass} size={16} aria-hidden />
            : <ChevronDownIcon className={cn('fnd-calendar__dropdown-icon', chevronClass)} size={14} aria-hidden />,
        DayButton: CalendarDayButton,
        ...components,
      }}
      {...props}
    />
  );
}

/*
 * shadcn's CalendarDayButton: the day carries its state as data attributes the
 * stylesheet reads (selected, today), and takes focus itself when the grid moves
 * the keyboard focus onto it.
 */
function CalendarDayButton({ className, day, modifiers, ...props }: DayButtonProps) {
  const ref = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (modifiers.focused) ref.current?.focus();
  }, [modifiers.focused]);
  return (
    <button
      ref={ref}
      data-slot="calendar-day"
      data-selected={modifiers.selected ? 'true' : undefined}
      data-today={modifiers.today ? 'true' : undefined}
      className={cn('fnd-calendar__day-button', className)}
      {...props}
    />
  );
}

export { Calendar, CalendarDayButton };
