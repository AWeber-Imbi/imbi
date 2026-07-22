import { useMemo } from 'react'

import SparkMD5 from 'spark-md5'

/**
 * Resolve a Gravatar URL for an email without rendering anything. The avatar
 * itself is rendered by `UserIdentity`, the single canonical identity widget;
 * this hook is its internal helper (callers should not use it directly).
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
