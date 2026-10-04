import type { ComponentProps } from 'react';
import { Command as CommandPrimitive } from 'cmdk';
import { SearchIcon } from 'lucide-react';

import { cn } from '@/lib/utils.js';

function Command({ className, ...props }: ComponentProps<typeof CommandPrimitive>) {
  return <CommandPrimitive data-slot="command" className={cn('flex flex-col text-popover-foreground', className)} {...props} />;
}

function CommandInput({ className, ...props }: ComponentProps<typeof CommandPrimitive.Input>) {
  return (
    <div data-slot="command-input-wrapper" className="fnd-combobox__search">
      <SearchIcon size={14} aria-hidden />
      <CommandPrimitive.Input data-slot="command-input" className={cn('outline-none', className)} {...props} />
    </div>
  );
}

function CommandList({ className, ...props }: ComponentProps<typeof CommandPrimitive.List>) {
  return <CommandPrimitive.List data-slot="command-list" className={cn('fnd-combobox__list', className)} {...props} />;
}

function CommandItem({ className, ...props }: ComponentProps<typeof CommandPrimitive.Item>) {
  return <CommandPrimitive.Item data-slot="command-item" className={cn('fnd-combobox__option', className)} {...props} />;
}

export { Command, CommandInput, CommandList, CommandItem };
