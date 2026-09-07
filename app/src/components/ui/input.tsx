import type { ComponentProps } from 'react';

import { cn } from '@/lib/utils.js';

function Input({ className, type, ...props }: ComponentProps<'input'>) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        'h-8 min-w-0 rounded-[var(--fnd-radius-control)] border border-input bg-[var(--fnd-surface)] px-3',
        'font-[inherit] text-[length:var(--fnd-size-small)] text-foreground',
        'transition-[border-color] duration-[var(--fnd-transition)] outline-none',
        'placeholder:text-muted-foreground',
        'hover:enabled:border-[var(--fnd-line-hover)]',
        'disabled:cursor-default disabled:opacity-55',
        'aria-invalid:border-[var(--fnd-mark-outside-line)]',
        className,
      )}
      {...props}
    />
  );
}

export { Input };
