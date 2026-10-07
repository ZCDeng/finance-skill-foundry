import type { ComponentProps } from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { Slot } from 'radix-ui';

import { cn } from '@/lib/utils.js';

const buttonVariants = cva(
  [
    'inline-flex shrink-0 items-center justify-center gap-2',
    'rounded-[var(--fnd-radius-control)] text-[length:var(--fnd-size-body)] leading-none whitespace-nowrap',
    'cursor-pointer transition-[border-color,background-color,color,opacity] duration-(--fnd-duration) ease-(--fnd-easing)',
    'disabled:cursor-default disabled:pointer-events-none',
    'aria-busy:cursor-progress',
    '[&_svg]:pointer-events-none [&_svg]:shrink-0',
  ].join(' '),
  {
    variants: {
      variant: {
        default:
          'border-0 bg-primary text-primary-foreground enabled:active:opacity-[0.88] disabled:opacity-40',
        outline: [
          'border border-border bg-transparent text-foreground',
          'enabled:hover:not-focus-visible:border-[var(--fnd-line-hover)] enabled:hover:bg-[var(--fnd-surface-strong)]',
          'enabled:active:bg-[var(--fnd-selection-surface)]',
          'disabled:opacity-55',
        ].join(' '),
        destructive: [
          'border border-[var(--fnd-warning-line)] bg-transparent text-[var(--fnd-warning)]',
          'enabled:hover:bg-[var(--fnd-warning-fill)]',
          'disabled:opacity-55',
        ].join(' '),
        ghost: [
          'border-0 bg-transparent text-[var(--fnd-muted)]',
          'enabled:hover:bg-[var(--fnd-surface-strong)] enabled:hover:text-foreground',
          'enabled:active:bg-[var(--fnd-selection-surface)]',
          'aria-pressed:bg-[var(--fnd-selection-surface)] aria-pressed:text-foreground',
          'data-[state=open]:bg-[var(--fnd-selection-surface)] data-[state=open]:text-foreground',
          'disabled:opacity-45',
        ].join(' '),
        link: [
          'h-auto self-start border-0 bg-transparent p-0 text-[var(--fnd-muted)] underline decoration-[var(--fnd-line)] underline-offset-4',
          'enabled:hover:text-foreground enabled:hover:no-underline',
          'disabled:opacity-55',
        ].join(' '),
        secondary: [
          'border-0 bg-secondary text-secondary-foreground',
          'enabled:hover:bg-[var(--fnd-selection-surface)]',
          'disabled:opacity-55',
        ].join(' '),
      },
      size: {
        default: 'h-[var(--fnd-button-height)] px-3.5',
        sm: 'h-8 px-2.5',
        lg: 'h-[var(--fnd-button-height)] px-3.5',
        icon: 'size-8 rounded-[6px] p-0',
        // A clickable chip (result period tabs, period shortcuts, candidate values): DESIGN.md 按钮与字段.
        chip: 'h-7 rounded-[var(--fnd-radius-chip)] px-2.5 text-[length:var(--fnd-size-label)]',
      },
    },
    compoundVariants: [
      {
        // Selected reads as an ink edge on the selection surface, never the solid primary or the gold.
        variant: 'outline',
        size: 'chip',
        className: [
          'aria-pressed:border-[var(--fnd-ink)] aria-pressed:bg-[var(--fnd-selection-surface)] aria-pressed:text-foreground',
          'aria-selected:border-[var(--fnd-ink)] aria-selected:bg-[var(--fnd-selection-surface)] aria-selected:text-foreground',
        ].join(' '),
      },
    ],
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
);

function Button({
  className,
  variant = 'default',
  size = 'default',
  asChild = false,
  ...props
}: ComponentProps<'button'> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
  }) {
  const Comp = asChild ? Slot.Root : 'button';
  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size }), variant === 'link' && 'h-auto p-0', className)}
      {...props}
    />
  );
}

export { Button, buttonVariants };
