import type { ComponentProps } from 'react';
import { ChevronDownIcon } from 'lucide-react';

import { cn } from '@/lib/utils.js';
import '../components.css';

/*
 * A real <select>: its menu is drawn by the platform, above every native view
 * in the window (see .fnd-picker). Only the chevron and field states are ours.
 */
function NativeSelect({
  className,
  wrapperClassName,
  ...props
}: ComponentProps<'select'> & { wrapperClassName?: string }) {
  return (
    <span data-slot="native-select-wrapper" className={cn('group/native-select fnd-native-select', wrapperClassName)}>
      <select data-slot="native-select" className={cn('fnd-field appearance-none pr-8', className)} {...props} />
      <ChevronDownIcon
        aria-hidden
        className="pointer-events-none absolute top-1/2 right-2.5 size-4 -translate-y-1/2 text-[var(--fnd-muted)] group-has-[select:disabled]/native-select:opacity-55"
      />
    </span>
  );
}

function NativeSelectOption(props: ComponentProps<'option'>) {
  return <option data-slot="native-select-option" {...props} />;
}

export { NativeSelect, NativeSelectOption };
