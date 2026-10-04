import type { ComponentProps } from 'react';
import { Switch as SwitchPrimitive } from 'radix-ui';

import { cn } from '@/lib/utils.js';

function Switch({ className, ...props }: ComponentProps<typeof SwitchPrimitive.Root>) {
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      className={cn(
        'peer inline-flex h-5 w-8 shrink-0 items-center cursor-pointer rounded-full border border-transparent p-px',
        'transition-[background-color] duration-(--fnd-duration) ease-(--fnd-easing)',
        'data-[state=unchecked]:bg-[var(--fnd-line-hover)] data-[state=checked]:bg-primary',
        'focus-visible:outline-1 focus-visible:outline-offset-1 focus-visible:outline-[var(--fnd-focus)]',
        'disabled:cursor-default disabled:opacity-45',
        className,
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        data-slot="switch-thumb"
        className={cn(
          'pointer-events-none block size-4 rounded-full bg-[var(--fnd-surface)]',
          'transition-transform duration-(--fnd-duration) ease-(--fnd-easing)',
          'data-[state=checked]:translate-x-3 data-[state=unchecked]:translate-x-0',
        )}
      />
    </SwitchPrimitive.Root>
  );
}

export { Switch };
