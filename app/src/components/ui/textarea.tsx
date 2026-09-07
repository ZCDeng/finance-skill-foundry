import type { ComponentProps } from 'react';

import { cn } from '@/lib/utils.js';

function Textarea({ className, ...props }: ComponentProps<'textarea'>) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        'min-h-20 w-full min-w-0 rounded-[var(--fnd-radius-control)] border border-input bg-[var(--fnd-surface)] px-3 py-2',
        'font-[inherit] text-[length:var(--fnd-size-small)] text-foreground',
        'transition-[border-color] duration-[var(--fnd-transition)] outline-none',
        'placeholder:text-muted-foreground',
        'hover:enabled:border-[var(--fnd-line-hover)]',
        'focus-visible:border-[var(--fnd-line-hover)] focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--fnd-line-hover)]',
        'disabled:cursor-default disabled:opacity-55',
        'aria-invalid:border-[var(--fnd-mark-outside-line)]',
        className,
      )}
      {...props}
    />
  );
}

export { Textarea };
