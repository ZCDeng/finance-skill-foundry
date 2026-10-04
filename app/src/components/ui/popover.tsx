import type { ComponentProps } from 'react';
import { Popover as PopoverPrimitive } from 'radix-ui';

import { cn } from '@/lib/utils.js';

function Popover(props: ComponentProps<typeof PopoverPrimitive.Root>) {
  return <PopoverPrimitive.Root data-slot="popover" {...props} />;
}

function PopoverTrigger(props: ComponentProps<typeof PopoverPrimitive.Trigger>) {
  return <PopoverPrimitive.Trigger data-slot="popover-trigger" {...props} />;
}

function PopoverAnchor(props: ComponentProps<typeof PopoverPrimitive.Anchor>) {
  return <PopoverPrimitive.Anchor data-slot="popover-anchor" {...props} />;
}

/*
 * Portalled to the document body and placed by Radix (flips and shifts at the
 * viewport edge). The page under the task bar is a native view, so a popover
 * only opens over this document; native menus stay on NativeSelect.
 */
function PopoverContent({ className, align = 'start', sideOffset = 6, collisionPadding = 12, ...props }: ComponentProps<typeof PopoverPrimitive.Content>) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        data-slot="popover-content"
        align={align}
        sideOffset={sideOffset}
        collisionPadding={collisionPadding}
        className={cn(
          'z-50 overflow-y-auto border border-border bg-popover text-popover-foreground outline-none',
          'rounded-[var(--fnd-radius-menu)] shadow-[var(--fnd-shadow-menu)]',
          'max-h-(--radix-popover-content-available-height) origin-(--radix-popover-content-transform-origin)',
          className,
        )}
        {...props}
      />
    </PopoverPrimitive.Portal>
  );
}

export { Popover, PopoverTrigger, PopoverAnchor, PopoverContent };
