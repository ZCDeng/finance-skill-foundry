import type { ComponentProps } from 'react';
import { Slot } from 'radix-ui';

import { cn } from '@/lib/utils.js';
import '../components.css';

/*
 * shadcn's Empty anatomy (empty / empty-header / empty-title / empty-description /
 * empty-content) on the FA empty-state classes: left-aligned, muted, no card.
 * Pass asChild to EmptyTitle to keep the page's heading level.
 */
function Empty({ className, ...props }: ComponentProps<'div'>) {
  return <div data-slot="empty" className={cn('fnd-empty', className)} {...props} />;
}

function EmptyHeader({ className, ...props }: ComponentProps<'div'>) {
  return <div data-slot="empty-header" className={cn('fnd-empty__header', className)} {...props} />;
}

function EmptyTitle({ className, asChild = false, ...props }: ComponentProps<'div'> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : 'div';
  return <Comp data-slot="empty-title" className={cn('fnd-empty__title', className)} {...props} />;
}

function EmptyDescription({ className, ...props }: ComponentProps<'p'>) {
  return <p data-slot="empty-description" className={cn('fnd-empty__description', className)} {...props} />;
}

function EmptyContent({ className, ...props }: ComponentProps<'div'>) {
  return <div data-slot="empty-content" className={cn('fnd-empty__content', className)} {...props} />;
}

export { Empty, EmptyHeader, EmptyTitle, EmptyDescription, EmptyContent };
