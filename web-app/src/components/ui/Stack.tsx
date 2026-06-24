import type { HTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

/** Horizontal flexbox, vertically centred. Thin helper over `flex items-center`. */
export function Row({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('flex items-center', className)} {...rest} />
}

/** Vertical flexbox. Thin helper over `flex flex-col`. */
export function Stack({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('flex flex-col', className)} {...rest} />
}
