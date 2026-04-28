/* eslint-disable react-refresh/only-export-components */
import { useMemo } from 'react'

import SparkMD5 from 'spark-md5'

interface GravatarProps {
  alt?: string
  className?: string
  defaultImage?:
    | '404'
    | 'identicon'
    | 'monsterid'
    | 'mp'
    | 'retro'
    | 'robohash'
    | 'wavatar'
  email: string
  size?: number
}

/**
 * Gravatar component - displays user avatar from Gravatar service based on email
 *
 * @param email - User's email address
 * @param size - Avatar size in pixels (default: 80)
 * @param className - Additional CSS classes
 * @param alt - Alt text for the image
 * @param defaultImage - Default image type if email has no Gravatar (default: 'mp' - mystery person)
 */
export function Gravatar({
  alt,
  className = '',
  defaultImage = 'mp',
  email,
  size = 80,
}: GravatarProps) {
  const gravatarUrl = useMemo(() => {
    const hash = SparkMD5.hash(email.toLowerCase().trim())
    return `https://www.gravatar.com/avatar/${hash}?s=${size}&d=${defaultImage}`
  }, [email, size, defaultImage])

  const displayName = alt || email.split('@')[0]

  return (
    <img
      alt={displayName}
      className={className}
      height={size}
      src={gravatarUrl}
      width={size}
    />
  )
}

/**
 * Hook to get Gravatar URL without rendering component
 */
export function useGravatarUrl(
  email: string,
  size: number = 80,
  defaultImage: string = 'mp',
): string {
  return useMemo(() => {
    const hash = SparkMD5.hash(email.toLowerCase().trim())
    return `https://www.gravatar.com/avatar/${hash}?s=${size}&d=${defaultImage}`
  }, [email, size, defaultImage])
}
