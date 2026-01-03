import { useMemo } from 'react'
import SparkMD5 from 'spark-md5'

interface GravatarProps {
  email: string
  size?: number
  className?: string
  alt?: string
  defaultImage?: 'mp' | '404' | 'identicon' | 'monsterid' | 'wavatar' | 'retro' | 'robohash'
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
  email,
  size = 80,
  className = '',
  alt,
  defaultImage = 'mp'
}: GravatarProps) {
  const gravatarUrl = useMemo(() => {
    const hash = SparkMD5.hash(email.toLowerCase().trim())
    return `https://www.gravatar.com/avatar/${hash}?s=${size}&d=${defaultImage}`
  }, [email, size, defaultImage])

  const displayName = alt || email.split('@')[0]

  return (
    <img
      src={gravatarUrl}
      alt={displayName}
      className={className}
      width={size}
      height={size}
    />
  )
}

/**
 * Hook to get Gravatar URL without rendering component
 */
export function useGravatarUrl(
  email: string,
  size: number = 80,
  defaultImage: string = 'mp'
): string {
  return useMemo(() => {
    const hash = SparkMD5.hash(email.toLowerCase().trim())
    return `https://www.gravatar.com/avatar/${hash}?s=${size}&d=${defaultImage}`
  }, [email, size, defaultImage])
}
