// Promotion pipelines derived from the flat environment list.
//
// Environments are one list ordered by sort_order, but that list may hold
// several independent pipelines: an environment whose `terminal` flag is
// true ends its pipeline, and the next environment by sort_order starts a
// new one (#285). Everything that walks "adjacent environments" as
// promotion steps must derive them here, so a step is never invented
// across the seam between two pipelines. Mirrors `imbi.common.environments`
// on the API side.

export interface ChainEnvironment {
  name: string
  sort_order?: null | number
  terminal?: boolean | null
}

/** The last environment of each pipeline. */
export function chainTerminals<T extends ChainEnvironment>(
  environments: T[],
): T[] {
  return splitChains(environments).map((chain) => chain[chain.length - 1])
}

/** The canonical environment ordering: sort_order, then name. */
export function sortByPipelineOrder<T extends ChainEnvironment>(
  environments: T[],
): T[] {
  return [...environments].sort((a, b) => {
    const orderDiff = (a.sort_order ?? 0) - (b.sort_order ?? 0)
    return orderDiff !== 0 ? orderDiff : a.name.localeCompare(b.name)
  })
}

/**
 * Sort into pipeline order and split into pipelines. A chain ends at
 * (and includes) each terminal environment; the next one starts a new
 * chain.
 */
export function splitChains<T extends ChainEnvironment>(
  environments: T[],
): T[][] {
  const chains: T[][] = []
  let chain: T[] = []
  for (const env of sortByPipelineOrder(environments)) {
    chain.push(env)
    if (env.terminal) {
      chains.push(chain)
      chain = []
    }
  }
  if (chain.length > 0) chains.push(chain)
  return chains
}

/**
 * Each environment's upstream within its own pipeline, keyed by slug.
 * `null` marks a pipeline's entry environment; a terminal environment is
 * never anyone's upstream.
 */
export function upstreamBySlug<T extends ChainEnvironment & { slug: string }>(
  environments: T[],
): Map<string, null | T> {
  const upstreams = new Map<string, null | T>()
  for (const chain of splitChains(environments)) {
    chain.forEach((env, index) => {
      upstreams.set(env.slug, index > 0 ? chain[index - 1] : null)
    })
  }
  return upstreams
}
