import type { ComponentProps } from 'react';
import { ChevronLeftIcon, ChevronRightIcon } from 'lucide-react';
import { DayPicker, getDefaultClassNames } from 'react-day-picker';
import { zhCN } from 'react-day-picker/locale';

import { cn } from '@/lib/utils.js';

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六'];

/*
 * shadcn's Calendar on react-day-picker, set for Chinese finance use: weeks
 * start on Monday, the caption reads "2026 年 8 月" and weekdays are one
 * character. Days are styled in financial-controls.css (.fnd-calendar*).
 */
function Calendar({ className, classNames, formatters, labels, ...props }: ComponentProps<typeof DayPicker>) {
  const defaults = getDefaultClassNames();
  return (
    <DayPicker
      data-slot="calendar"
      locale={zhCN}
      weekStartsOn={1}
      showOutsideDays={false}
      className={cn('fnd-calendar', className)}
      formatters={{
        formatCaption: (date) => `${date.getFullYear()} 年 ${date.getMonth() + 1} 月`,
        formatWeekdayName: (date) => WEEKDAYS[date.getDay()],
        ...formatters,
      }}
      labels={{
        labelPrevious: () => '上一月',
        labelNext: () => '下一月',
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
          : <ChevronRightIcon className={chevronClass} size={16} aria-hidden />,
      }}
      {...props}
    />
  );
}

export { Calendar };
