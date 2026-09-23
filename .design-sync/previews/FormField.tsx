import {
  FormField,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from 'imbi-ui'

export const Default = () => (
  <div className="w-80">
    <FormField htmlFor="ai-model-name" label="Display name">
      <Input
        id="ai-model-name"
        placeholder="What engineers see in the model picker"
      />
    </FormField>
  </div>
)

export const RequiredWithDescription = () => (
  <div className="w-80">
    <FormField
      description="The identifier Imbi sends to the provider. For self-hosted gateways, a full inference URL is accepted."
      htmlFor="ai-model-id"
      label="Model name or URL"
      required
    >
      <Input
        className="font-mono"
        defaultValue="claude-opus-5-5"
        id="ai-model-id"
      />
    </FormField>
  </div>
)

export const WithError = () => (
  <div className="w-80">
    <FormField
      error="Slug may only contain lowercase letters, numbers, and dashes"
      htmlFor="project-type-slug"
      label="Slug"
      required
      touched
    >
      <Input
        aria-invalid
        className="border-red-500 font-mono"
        defaultValue="HTTP API"
        id="project-type-slug"
      />
    </FormField>
  </div>
)

export const AdminForm = () => (
  <div className="w-96 space-y-4">
    <FormField htmlFor="env-name" label="Name" required>
      <Input defaultValue="Production" id="env-name" />
    </FormField>
    <FormField label="Team" required>
      <Select defaultValue="platform">
        <SelectTrigger aria-label="Team">
          <SelectValue placeholder="Select a team" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="platform">Platform Engineering</SelectItem>
          <SelectItem value="data">Data Services</SelectItem>
        </SelectContent>
      </Select>
    </FormField>
    <FormField
      description="Shown on the environment badge tooltip."
      htmlFor="env-description"
      label="Description"
    >
      <Textarea
        className="resize-none"
        defaultValue="Customer-facing traffic in us-east-1."
        id="env-description"
      />
    </FormField>
  </div>
)
