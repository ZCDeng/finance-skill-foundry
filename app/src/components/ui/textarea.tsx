import type { ComponentProps } from 'react';

import { cn } from '@/lib/utils.js';
import '../components.css';

function Textarea({ className, ...props }: ComponentProps<'textarea'>) {
  return (
    <textarea
      data-slot="textarea"
      className={cn('fnd-field', className)}
      {...props}
    />
  );
}

export { Textarea };
