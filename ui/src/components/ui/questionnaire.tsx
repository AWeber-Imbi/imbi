import type * as React from 'react'

import { Questionnaire as QuestionnairePrimitive } from '@shadcn/react/questionnaire'
import { Check } from 'lucide-react'

import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'

function Questionnaire({
  className,
  ...props
}: React.ComponentProps<typeof QuestionnairePrimitive.Root>) {
  return (
    <QuestionnairePrimitive.Root
      className={cn('flex w-full min-w-0 flex-col gap-4', className)}
      data-slot="questionnaire"
      {...props}
    />
  )
}

function QuestionnaireActions({
  className,
  ...props
}: React.ComponentProps<'div'>) {
  return (
    <div
      className={cn('flex items-center gap-2', className)}
      data-slot="questionnaire-actions"
      {...props}
    />
  )
}

function QuestionnaireChoice({
  children,
  className,
  ...props
}: React.ComponentProps<typeof QuestionnairePrimitive.Choice>) {
  return (
    <QuestionnairePrimitive.Choice
      className={cn(
        'group/questionnaire-choice relative flex min-h-11 cursor-pointer items-start gap-2.5 rounded-lg border border-secondary bg-primary px-3 py-2.5 text-start text-sm transition-colors outline-none select-none hover:bg-secondary has-[>input:focus-visible]:border-ring has-[>input:focus-visible]:ring-3 has-[>input:focus-visible]:ring-ring/50 data-invalid:border-destructive sm:min-h-0 data-checked:border-action data-checked:bg-secondary',
        'data-disabled:pointer-events-none data-disabled:cursor-not-allowed data-disabled:opacity-50',
        className,
      )}
      data-slot="questionnaire-choice"
      {...props}
    >
      <QuestionnairePrimitive.ChoiceInput
        className="absolute inset-0 z-10 size-full cursor-pointer opacity-0"
        data-slot="questionnaire-choice-input"
      />
      <span
        aria-hidden="true"
        className="border-muted-foreground group-data-checked/questionnaire-choice:border-action group-data-checked/questionnaire-choice:bg-action group-data-checked/questionnaire-choice:text-action-foreground pointer-events-none relative flex size-4 shrink-0 translate-y-0.5 items-center justify-center rounded-[4px] border group-data-[type=radio]/questionnaire-choice:rounded-full"
        data-slot="questionnaire-choice-indicator"
      >
        <span className="hidden size-2 rounded-full bg-current group-data-checked/questionnaire-choice:block group-data-[type=checkbox]/questionnaire-choice:hidden" />
        <Check className="hidden size-3.5 group-data-checked/questionnaire-choice:block group-data-[type=radio]/questionnaire-choice:hidden" />
      </span>
      <QuestionnairePrimitive.ChoiceLabel
        className="flex min-w-0 flex-1 flex-col gap-0.5 leading-snug"
        data-slot="questionnaire-choice-label"
      >
        {children}
      </QuestionnairePrimitive.ChoiceLabel>
    </QuestionnairePrimitive.Choice>
  )
}

function QuestionnaireChoices({
  className,
  ...props
}: React.ComponentProps<typeof QuestionnairePrimitive.Choices>) {
  return (
    <QuestionnairePrimitive.Choices
      className={cn('grid min-w-0 gap-2', className)}
      data-slot="questionnaire-choices"
      {...props}
    />
  )
}

function QuestionnaireDescription({
  className,
  ...props
}: React.ComponentProps<typeof QuestionnairePrimitive.Description>) {
  return (
    <QuestionnairePrimitive.Description
      className={cn('text-sm text-pretty text-muted-foreground', className)}
      data-slot="questionnaire-description"
      {...props}
    />
  )
}

function QuestionnaireError({
  className,
  ...props
}: React.ComponentProps<typeof QuestionnairePrimitive.Error>) {
  return (
    <QuestionnairePrimitive.Error
      className={cn('text-sm text-destructive', className)}
      data-slot="questionnaire-error"
      {...props}
    />
  )
}

function QuestionnaireInput({
  className,
  ...props
}: React.ComponentProps<typeof QuestionnairePrimitive.Input>) {
  return (
    <QuestionnairePrimitive.Input
      className={cn(
        'min-h-11 w-full min-w-0 rounded-lg border border-secondary bg-primary px-3 py-1 text-base transition-[color,box-shadow,background-color] outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive data-filled:border-action sm:min-h-9 md:text-sm',
        className,
      )}
      data-slot="questionnaire-input"
      {...props}
    />
  )
}

function QuestionnaireItem({
  className,
  ...props
}: React.ComponentProps<typeof QuestionnairePrimitive.Item>) {
  return (
    <QuestionnairePrimitive.Item
      className={cn(
        'flex min-w-0 flex-col gap-3 border-0 p-0 outline-none',
        className,
      )}
      data-slot="questionnaire-item"
      {...props}
    />
  )
}

function QuestionnaireSubmit({
  children,
  className,
  size = 'sm',
  variant = 'default',
  ...props
}: React.ComponentProps<typeof QuestionnairePrimitive.Submit> & {
  size?: 'default' | 'lg' | 'sm'
  variant?: 'default' | 'outline'
}) {
  return (
    <QuestionnairePrimitive.Submit
      className={cn(buttonVariants({ size, variant }), className)}
      data-slot="questionnaire-submit"
      {...props}
    >
      {children ?? 'Submit'}
    </QuestionnairePrimitive.Submit>
  )
}

function QuestionnaireTitle({
  className,
  ...props
}: React.ComponentProps<typeof QuestionnairePrimitive.Title>) {
  return (
    <QuestionnairePrimitive.Title
      className={cn('text-sm leading-snug font-medium text-pretty', className)}
      data-slot="questionnaire-title"
      {...props}
    />
  )
}

export {
  Questionnaire,
  QuestionnaireActions,
  QuestionnaireChoice,
  QuestionnaireChoices,
  QuestionnaireDescription,
  QuestionnaireError,
  QuestionnaireInput,
  QuestionnaireItem,
  QuestionnaireSubmit,
  QuestionnaireTitle,
}
