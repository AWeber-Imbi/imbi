/** Canonical project URL: ``/projects/<slug>/<id>[/<rest>...]``. */
export function projectPath(
  project: { id: string; slug: string },
  ...rest: string[]
): string {
  return ['/projects', project.slug, project.id, ...rest].join('/')
}

// Project IDs are 21-character nanoids. No tab slug is that long, so the
// second path segment tells ``/projects/<slug>/<id>/...`` apart from the
// legacy ``/projects/<id>/<tab>/...`` form.
const PROJECT_ID = /^[\w-]{21}$/

/**
 * Split ``/projects/*`` segments into the project ID and the remainder,
 * accepting both the slug form and the legacy ID-first form (no slug).
 */
export function parseProjectSegments(segments: string[]): {
  projectId: string
  rest: string[]
  slug?: string
} {
  const [first = '', second, ...tail] = segments
  if (second !== undefined && PROJECT_ID.test(second)) {
    return { projectId: second, rest: tail, slug: first }
  }
  return { projectId: first, rest: segments.slice(1) }
}
