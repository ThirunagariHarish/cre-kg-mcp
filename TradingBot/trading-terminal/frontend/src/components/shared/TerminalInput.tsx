import React from 'react'
import clsx from 'clsx'
import { inputVariants } from '@/design-system/components'
import type { VariantProps } from 'class-variance-authority'

interface TerminalInputProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'size'>,
    VariantProps<typeof inputVariants> {
  label?: string
  error?: string
  helpText?: string
  leftAdornment?: React.ReactNode
  rightAdornment?: React.ReactNode
  containerClassName?: string
}

export default function TerminalInput({
  label,
  error,
  helpText,
  leftAdornment,
  rightAdornment,
  variant,
  inputSize = 'md',
  mono = false,
  containerClassName,
  className,
  id,
  ...props
}: TerminalInputProps) {
  const resolvedVariant = error ? 'error' : variant

  return (
    <div className={clsx('flex flex-col gap-0.5', containerClassName)}>
      {label && (
        <label
          htmlFor={id}
          className="font-mono text-[0.55rem] text-text-muted uppercase tracking-widest"
        >
          {label}
        </label>
      )}

      <div className="relative flex items-center">
        {leftAdornment && (
          <div className="absolute left-2 flex items-center text-text-muted">
            {leftAdornment}
          </div>
        )}

        <input
          id={id}
          className={clsx(
            inputVariants({ variant: resolvedVariant, inputSize, mono }),
            leftAdornment && 'pl-7',
            rightAdornment && 'pr-7',
            className
          )}
          {...props}
        />

        {rightAdornment && (
          <div className="absolute right-2 flex items-center text-text-muted">
            {rightAdornment}
          </div>
        )}
      </div>

      {error && (
        <p className="font-mono text-[0.55rem] text-negative">{error}</p>
      )}

      {helpText && !error && (
        <p className="font-mono text-[0.55rem] text-text-muted">{helpText}</p>
      )}
    </div>
  )
}
