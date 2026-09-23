import { Label, Slider } from 'imbi-ui'

export const Default = () => (
  <div className="w-64">
    <Label className="text-muted-foreground mb-1.5 block text-xs">
      Similarity threshold
    </Label>
    <Slider aria-label="Similarity threshold" defaultValue={[0.75]} max={1.0} min={0.1} step={0.05} />
    <span className="text-muted-foreground mt-1 block font-mono text-xs">
      0.75 cosine
    </span>
  </div>
)

export const SearchFilters = () => (
  <div className="w-64 space-y-4">
    <div>
      <Label className="text-muted-foreground mb-1.5 block text-xs">
        Similarity threshold
      </Label>
      <Slider aria-label="Similarity threshold" defaultValue={[0.3]} max={1.0} min={0.1} step={0.05} />
      <span className="text-muted-foreground mt-1 block font-mono text-xs">
        0.30 cosine
      </span>
    </div>
    <div>
      <Label className="text-muted-foreground mb-1.5 block text-xs">
        Max results
      </Label>
      <Slider aria-label="Max results" defaultValue={[25]} max={100} min={5} step={5} />
      <span className="text-muted-foreground mt-1 block font-mono text-xs">
        25
      </span>
    </div>
  </div>
)

export const Disabled = () => (
  <div className="w-64">
    <Label className="text-muted-foreground mb-1.5 block text-xs">
      Similarity threshold (locked by admin)
    </Label>
    <Slider aria-label="Similarity threshold (locked by admin)" defaultValue={[0.75]} disabled max={1.0} min={0.1} step={0.05} />
  </div>
)
