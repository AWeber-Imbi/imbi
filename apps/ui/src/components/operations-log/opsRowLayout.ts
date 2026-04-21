// Shared 9-column grid for both Stream and Release rows so their columns
// line up vertically. The env/train column (col 6) is rendered rowspan=2
// so single-line envs stay centred and multi-line release trains get
// room alongside the description row.
//   rail | icon | project | version | desc | env/train | avatar | time | chevron
export const OPS_ROW_GRID =
  '4px 26px minmax(140px,180px) auto minmax(0,1fr) minmax(560px,4fr) 46px 44px 20px'

export const OPS_ROW_PAD = 'py-4 pr-3.5 pl-0'
