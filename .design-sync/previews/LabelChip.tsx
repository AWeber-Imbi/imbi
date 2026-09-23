import { LabelChip } from 'imbi-ui'

const SWATCHES = [
  { hex: '#C86B5E', name: 'Clay' },
  { hex: '#D98847', name: 'Ember' },
  { hex: '#C9A227', name: 'Honey' },
  { hex: '#6B9A3F', name: 'Moss' },
  { hex: '#5A89C9', name: 'Dusk' },
  { hex: '#8C82D4', name: 'Lilac' },
  { hex: '#C96B97', name: 'Rose' },
  { hex: '#7A7873', name: 'Stone' },
]

export const Default = () => <LabelChip hex="#C86B5E">production</LabelChip>

export const Palette = () => (
  <div className="flex flex-wrap gap-2">
    {SWATCHES.map((s) => (
      <LabelChip hex={s.hex} key={s.name} title={s.hex}>
        {s.name}
      </LabelChip>
    ))}
  </div>
)

export const EnvironmentChips = () => (
  <div className="flex flex-wrap items-center gap-1.5">
    <LabelChip hex="#5A89C9">testing</LabelChip>
    <LabelChip hex="#C9A227">staging</LabelChip>
    <LabelChip hex="#C86B5E">production</LabelChip>
  </div>
)

export const BlueprintTypes = () => (
  <div className="flex w-80 flex-col gap-2 text-sm">
    <div className="flex items-center justify-between gap-6">
      <span className="text-primary">Service Metadata</span>
      <LabelChip className="font-mono" hex="#8C82D4">
        Project
      </LabelChip>
    </div>
    <div className="flex items-center justify-between gap-6">
      <span className="text-primary">Deployment Attributes</span>
      <LabelChip className="font-mono" hex="#6B9A3F">
        DEPLOYED_IN
      </LabelChip>
    </div>
    <div className="flex items-center justify-between gap-6">
      <span className="text-primary">Team Ownership</span>
      <LabelChip className="font-mono" hex="#D98847">
        Team
      </LabelChip>
    </div>
  </div>
)
