import type { ComponentProps } from 'react';
import { HoverCard as HoverCardPrimitive } from 'radix-ui';

import { cn } from '@/lib/utils.js';

function HoverCard(props: ComponentProps<typeof HoverCardPrimitive.Root>) {
  return <HoverCardPrimitive.Root data-slot="hover-card" {...props} />;
}

function HoverCardTrigger(props: ComponentProps<typeof HoverCardPrimitive.Trigger>) {
  return <HoverCardPrimitive.Trigger data-slot="hover-card-trigger" {...props} />;
}

/*
 * A pointer-only preview, portalled and placed by Radix like a popover. Radix opens it on hover and on
 * focus of the trigger; whatever it shows must also be reachable another way, since hover is not.
 * The menu surface (border, shadow) is drawn here; content that scrolls brings its own inner scroller.
 */
function HoverCardContent({ className, align = 'start', sideOffset = 6, collisionPadding = 12, ...props }: ComponentProps<typeof HoverCardPrimitive.Content>) {
  return (
    <HoverCardPrimitive.Portal>
      <HoverCardPrimitive.Content
        data-slot="hover-card-content"
        align={align}
        sideOffset={sideOffset}
        collisionPadding={collisionPadding}
        className={cn(
          'z-50 flex overflow-hidden border border-border bg-popover text-popover-foreground outline-none',
          'rounded-[var(--fnd-radius-container)] shadow-[var(--fnd-shadow-menu)]',
          'max-h-(--radix-hover-card-content-available-height)',
          className,
        )}
        {...props}
      />
    </HoverCardPrimitive.Portal>
  );
}

export { HoverCard, HoverCardTrigger, HoverCardContent };
