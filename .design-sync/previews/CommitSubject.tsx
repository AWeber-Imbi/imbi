import { CommitSubject } from 'imbi-ui'

const COMMIT_URL = 'https://github.com/AWeber-Imbi/imbi/commit/0b1d6c0b9f3e4a2d8c71e5b6a4f09d3c2e1b7a55'

export const LinkedReference = () => (
  <CommitSubject
    className="text-primary text-sm"
    commitUrl={COMMIT_URL}
    message="Fix retry on AGE connection loss (#326)"
  />
)

export const MultipleReferences = () => (
  <CommitSubject
    className="text-primary text-sm"
    commitUrl={COMMIT_URL}
    message={'Merge release notes editor (#329) and signed tags (#330)\n\nSquashed commit body is not rendered.'}
  />
)

export const PlainText = () => (
  <CommitSubject
    className="text-primary text-sm"
    commitUrl={null}
    message="Keep recipient addresses out of email audit errors (#331)"
  />
)

export const CommitList = () => (
  <ul className="border-tertiary w-full max-w-xl rounded-md border">
    {[
      ['0b1d6c0', 'Keep recipient addresses out of email audit errors (#331)'],
      ['6141081', 'Create the email_audit ClickHouse table (#328)'],
      ['9c6d533', 'Add a GitHub-style markdown editor for release notes (#329)'],
      ['f4a630f', 'Fix test formatting'],
    ].map(([sha, message]) => (
      <li
        className="border-tertiary flex min-w-0 items-center gap-3 border-b px-3 py-1.5 last:border-b-0"
        key={sha}
      >
        <span className="text-secondary shrink-0 font-mono text-xs">{sha}</span>
        <CommitSubject
          className="text-primary min-w-0 flex-1 truncate text-sm"
          commitUrl={COMMIT_URL}
          message={message}
        />
      </li>
    ))}
  </ul>
)
