import type { ComponentProps } from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { Slot } from 'radix-ui';

import { cn } from '@/lib/utils.js';

const buttonVariants = cva(
  [
    'inline-flex shrink-0 items-center justify-center gap-1.5',
    'rounded-[var(--fnd-radius-control)] font-[inherit] text-[length:var(--fnd-size-small)] leading-none whitespace-nowrap',
    'cursor-pointer outline-none transition-[border-color,background-color,color,opacity] duration-[var(--fnd-transition)]',
    'focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--fnd-line-hover)]',
    'disabled:cursor-default disabled:pointer-events-none',
    'aria-busy:cursor-progress',
    '[&_svg]:pointer-events-none [&_svg]:shrink-0',
  ].join(' '),
  {
    variants: {
      variant: {
        default:
          'border-0 bg-primary text-primary-foreground disabled:opacity-40 active:enabled:opacity-[0.88]',
        outline: [
          'border border-border bg-transparent text-foreground',
          'hover:enabled:border-[var(--fnd-line-hover)] hover:enabled:bg-[var(--fnd-surface-strong)]',
          'active:enabled:bg-[var(--fnd-selection-surface)]',
          'disabled:opacity-55',
        ].join(' '),
        destructive: [
          'border border-[var(--fnd-mark-outside-line)] bg-transparent text-[var(--fnd-mark-outside)]',
          'hover:enabled:bg-[var(--fnd-mark-outside-fill)]',
          'disabled:opacity-55',
        ].join(' '),
        ghost: [
          'border-0 bg-transparent text-[var(--fnd-muted)]',
          'hover:enabled:bg-[var(--fnd-surface-strong)] hover:enabled:text-foreground',
          'active:enabled:bg-[var(--fnd-selection-surface)]',
          'aria-pressed:bg-[var(--fnd-selection-surface)] aria-pressed:text-[var(--fnd-accent-text)]',
          'disabled:opacity-45',
        ].join(' '),
        link: [
          'h-auto self-start border-0 bg-transparent p-0 text-[var(--fnd-muted)] underline decoration-[var(--fnd-line)] underline-offset-4',
          'hover:enabled:text-foreground hover:enabled:no-underline',
          'disabled:opacity-55',
        ].join(' '),
        secondary: [
          'border-0 bg-secondary text-secondary-foreground',
          'hover:enabled:bg-[var(--fnd-selection-surface)]',
          'disabled:opacity-55',
        ].join(' '),
      },
      size: {
        default: 'h-8 px-3.5',
        sm: 'h-8 px-2.5',
        lg: 'h-8 px-3.5',
        icon: 'size-8 rounded-[6px] p-0',
      },
    },
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
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  );
}

export { Button, buttonVariants };
