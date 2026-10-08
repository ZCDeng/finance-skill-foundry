import type { ComponentProps } from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { Tabs as TabsPrimitive } from 'radix-ui';

import { cn } from '@/lib/utils.js';

function Tabs({
  className,
  orientation = 'horizontal',
  ...props
}: ComponentProps<typeof TabsPrimitive.Root>) {
  return (
    <TabsPrimitive.Root
      data-slot="tabs"
      data-orientation={orientation}
      orientation={orientation}
      className={cn('group/tabs flex data-[orientation=horizontal]:flex-col', className)}
      {...props}
    />
  );
}

const tabsListVariants = cva(
  'group/tabs-list inline-flex w-fit items-center text-[var(--fnd-muted)]',
  {
    variants: {
      variant: {
        default: 'h-8 gap-1 rounded-[var(--fnd-radius-control)] bg-muted p-0.5',
        line: 'h-auto gap-[22px] rounded-none bg-transparent p-0',
      },
    },
    defaultVariants: {
      variant: 'line',
    },
  },
);

function TabsList({
  className,
  variant = 'line',
  children,
  ...props
}: ComponentProps<typeof TabsPrimitive.List> & VariantProps<typeof tabsListVariants>) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      data-variant={variant}
      className={cn(tabsListVariants({ variant }), className)}
      {...props}
    >
      {children}
      {/* Base UI's Tabs.Indicator, drawn in CSS: it anchors to the active trigger and slides when that changes (components.css). */}
      {variant === 'line' ? <span data-slot="tabs-indicator" aria-hidden /> : null}
    </TabsPrimitive.List>
  );
}

function TabsTrigger({ className, ...props }: ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      data-slot="tabs-trigger"
      className={cn(
        'relative inline-flex items-center justify-center gap-1.5 whitespace-nowrap',
        'border-0 bg-transparent text-[length:var(--fnd-size-body)]',
        'cursor-pointer text-[var(--fnd-muted)] transition-[color] duration-(--fnd-duration) ease-(--fnd-easing)',
        'enabled:hover:text-foreground',
        'disabled:cursor-default disabled:opacity-55',
        'data-[state=active]:text-foreground',
        '[&_span]:text-[length:var(--fnd-size-label)] [&_span]:text-[var(--fnd-muted)]',
        className,
      )}
      {...props}
    />
  );
}

function TabsContent({ className, ...props }: ComponentProps<typeof TabsPrimitive.Content>) {
  return (
    <TabsPrimitive.Content data-slot="tabs-content" className={cn('flex-1 outline-none', className)} {...props} />
  );
}

export { Tabs, TabsList, TabsTrigger, TabsContent, tabsListVariants };
