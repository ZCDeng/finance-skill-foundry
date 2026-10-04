import type { ComponentProps } from 'react';
import { CheckIcon } from 'lucide-react';
import { Checkbox as CheckboxPrimitive } from 'radix-ui';

import { cn } from '@/lib/utils.js';

function Checkbox({ className, ...props }: ComponentProps<typeof CheckboxPrimitive.Root>) {
  return (
    <CheckboxPrimitive.Root
      data-slot="checkbox"
      className={cn(
        'peer inline-grid size-4 shrink-0 place-content-center cursor-pointer',
        'rounded-[4px] border border-[var(--fnd-line-hover)] bg-[var(--fnd-surface)] text-primary-foreground',
        'transition-[border-color,background-color] duration-(--fnd-duration) ease-(--fnd-easing)',
        'data-[state=checked]:border-primary data-[state=checked]:bg-primary',
        'aria-invalid:border-[var(--fnd-warning-line)]',
        'focus-visible:outline-1 focus-visible:outline-offset-1 focus-visible:outline-[var(--fnd-focus)]',
        'disabled:cursor-default disabled:opacity-45',
        className,
      )}
      {...props}
    >
      <CheckboxPrimitive.Indicator data-slot="checkbox-indicator" className="grid place-content-center text-current">
        <CheckIcon className="size-3.5" strokeWidth={2} aria-hidden />
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  );
}

export { Checkbox };
