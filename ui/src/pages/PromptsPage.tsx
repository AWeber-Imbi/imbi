import { CommandBar } from '@/components/CommandBar'
import { Navigation } from '@/components/Navigation'
import { PromptCMS } from '@/components/prompts/PromptCMS'
import { usePageTitle } from '@/hooks/usePageTitle'

export function PromptsPage() {
  usePageTitle('Prompts')
  return (
    <div className="bg-tertiary text-primary min-h-screen">
      <Navigation currentView="prompts" />
      <main className="pt-16">
        <PromptCMS />
      </main>
      <CommandBar />
    </div>
  )
}
