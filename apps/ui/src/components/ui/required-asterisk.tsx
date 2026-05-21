/**
 * Required-field indicator. Use after a field's label text:
 * `<label>Name <RequiredAsterisk /></label>`.
 *
 * Renders an `aria-hidden` asterisk in the danger color. Pair with
 * `aria-required` on the field itself for accessible required state.
 */
export function RequiredAsterisk() {
  return (
    <span aria-hidden="true" className="text-danger">
      *
    </span>
  )
}
