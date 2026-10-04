import type { ComponentProps } from 'react';

import { cn } from '@/lib/utils.js';

/*
 * shadcn's Field anatomy (field / field-label / field-description / field-error)
 * on the FA control classes in financial-controls.css. Invalid state is
 * data-invalid on the field and aria-invalid on the control.
 */
function Field({ className, ...props }: ComponentProps<'div'>) {
  return <div data-slot="field" className={cn('fnd-control', className)} {...props} />;
}

function FieldLabel({ className, ...props }: ComponentProps<'label'>) {
  return <label data-slot="field-label" className={cn('fnd-control__label', className)} {...props} />;
}

/** A field caption that names a group rather than one control (no htmlFor target). */
function FieldTitle({ className, ...props }: ComponentProps<'span'>) {
  return <span data-slot="field-label" className={cn('fnd-control__label', className)} {...props} />;
}

function FieldDescription({ className, ...props }: ComponentProps<'span'>) {
  return <span data-slot="field-description" className={cn('fnd-control__help', className)} {...props} />;
}

function FieldError({ className, ...props }: ComponentProps<'span'>) {
  return <span data-slot="field-error" className={cn('fnd-control__error', className)} {...props} />;
}

export { Field, FieldLabel, FieldTitle, FieldDescription, FieldError };
