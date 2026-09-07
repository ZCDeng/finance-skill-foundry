import type { ComponentProps } from 'react';

import { cn } from '@/lib/utils.js';
import '../components.css';

function Input({ className, type, ...props }: ComponentProps<'input'>) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn('fnd-field', className)}
      {...props}
    />
  );
}

export { Input };
