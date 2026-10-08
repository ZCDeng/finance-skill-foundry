import type { ComponentProps } from 'react';

import { cn } from '@/lib/utils.js';

/*
 * shadcn's Skeleton: a block in the strong surface that breathes while
 * something loads (components.css .fnd-skeleton). Decorative; the words that
 * say what is loading sit next to it for assistive technology.
 */
function Skeleton({ className, ...props }: ComponentProps<'div'>) {
  return <div data-slot="skeleton" aria-hidden className={cn('fnd-skeleton', className)} {...props} />;
}

export { Skeleton };
