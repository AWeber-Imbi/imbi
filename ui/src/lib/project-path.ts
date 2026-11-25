/**
 * Canonical project URL: ``/projects/<slug>/<id>[/<rest>...]``. The API does
 * not restrict slug characters, so the slug is encoded to keep ``/``, ``?``
 * and ``#`` inside its own path segment.
 */
export function projectPath(
  project: { id: string; slug: string },
  ...rest: string[]
): string {
  return [
    '/projects',
    encodeURIComponent(project.slug),
    project.id,
    ...rest,
  ].join('/')
}

// Project IDs are 21-character nanoids. No tab slug is that long, so the
// second path segment tells ``/projects/<slug>/<id>/...`` apart from the
// legacy ``/projects/<id>/<tab>/...`` form.
const PROJECT_ID = /^[\w-]{21}$/

/**
 * Split a raw (still encoded) ``/projects/...`` pathname into the project ID
 * and the remainder, accepting both the slug form and the legacy ID-first
 * form (no slug). Segments are decoded after the split, so an encoded ``/``
 * in a slug does not move the segment boundaries.
 */
export function parseProjectPath(pathname: string): {
  projectId: string
  rest: string[]
  slug?: string
} {
  const segments = pathname.split('/').filter(Boolean).slice(1).map(decode)
  const [first = '', second, ...tail] = segments
  if (second !== undefined && PROJECT_ID.test(second)) {
    return { projectId: second, rest: tail, slug: first }
  }
  return { projectId: first, rest: segments.slice(1) }
}

function decode(segment: string): string {
  try {
    return decodeURIComponent(segment)
  } catch {
    return segment
  }
}
