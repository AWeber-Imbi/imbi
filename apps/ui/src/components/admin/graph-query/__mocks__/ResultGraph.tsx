/**
 * Vitest auto-mock — reagraph pulls in WebGL which jsdom can't render.
 */
export function ResultGraph() {
  return <div data-testid="result-graph" />
}
