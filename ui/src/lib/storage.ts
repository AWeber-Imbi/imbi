/**
 * Web Storage that never throws. A browser can block storage (a
 * `SecurityError` on access) or fill it (a `QuotaExceededError` on
 * write). Here a read gives `null` and a write does nothing, so the
 * page still renders and the value applies until the page closes.
 */
function safe(store: () => Storage) {
  return {
    getItem(key: string): null | string {
      try {
        return store().getItem(key)
      } catch {
        return null
      }
    },
    removeItem(key: string): void {
      try {
        store().removeItem(key)
      } catch {
        // Blocked: there is nothing stored to remove.
      }
    },
    setItem(key: string, value: string): void {
      try {
        store().setItem(key, value)
      } catch {
        // Blocked or full: keep the value in page state only.
      }
    },
  }
}

export const storage = safe(() => window.localStorage)
export const session = safe(() => window.sessionStorage)
