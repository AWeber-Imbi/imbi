/* eslint-disable react-refresh/only-export-components */
import type { HTMLAttributes, ReactNode } from 'react'

import { cva, type VariantProps } from 'class-variance-authority'
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle,
  Info,
  type LucideIcon,
} from 'lucide-react'

import { cn } from '@/lib/utils'

const alertVariants = cva(
  'flex items-start gap-3 rounded-lg border p-4 text-sm',
  {
    defaultVariants: {
      variant: 'info',
    },
    variants: {
      variant: {
        danger: 'border-danger bg-danger text-danger',
        info: 'border-info bg-info text-info',
        success: 'border-success bg-success text-success',
        warning: 'border-warning bg-warning text-warning',
      },
    },
  },
)

const ICON_FOR_VARIANT: Record<
  NonNullable<VariantProps<typeof alertVariants>['variant']>,
  LucideIcon
> = {
  danger: AlertCircle,
  info: Info,
  success: CheckCircle,
  warning: AlertTriangle,
}

export interface AlertProps
  extends
    Omit<HTMLAttributes<HTMLDivElement>, 'title'>,
    VariantProps<typeof alertVariants> {
  /** Override the default icon for the variant. Pass `null` to suppress it. */
  icon?: LucideIcon | null
  /** Optional bold lead-in displayed above the body. */
  title?: ReactNode
}

/**
 * Inline alert / banner with semantic variants. Use for informational,
 * warning, success, or danger messages embedded in a page. For dedicated
 * error displays prefer `<ErrorBanner>`, which formats API errors.
 */
export function Alert({
  children,
  className,
  icon,
  title,
  variant,
  ...props
}: AlertProps) {
  const Icon =
    icon === null ? null : (icon ?? ICON_FOR_VARIANT[variant ?? 'info'])
  return (
    <div
      className={cn(alertVariants({ variant }), className)}
      role="alert"
      {...props}
    >
      {Icon && <Icon className="mt-0.5 size-5 shrink-0" />}
      <div className="flex-1">
        {title && <div className="mb-1 font-medium">{title}</div>}
        <div>{children}</div>
      </div>
    </div>
  )
}

export { alertVariants }
