import { describe, expect, it } from 'vitest'

import {
  pullRequestRefs,
  repoWebUrl,
  splitPullRequestRefs,
} from '../commit-refs'

const GH = 'https://github.com/aweber-imbi/imbi'
const GHE = 'https://aweber.ghe.com/apis/address-verification'

describe('repoWebUrl', () => {
  it('derives the repo root from a commit URL', () => {
    expect(repoWebUrl(`${GH}/commit/c5c7e0af`)).toBe(GH)
    expect(repoWebUrl(`${GHE}/commit/deadbeef`)).toBe(GHE)
  })

  it('rejects URLs that are not commit URLs', () => {
    expect(repoWebUrl(GH)).toBeNull()
    expect(repoWebUrl(`${GH}/pull/173`)).toBeNull()
    expect(repoWebUrl('https://github.com/commit/abc')).toBeNull()
  })

  it('rejects missing and unsafe URLs', () => {
    expect(repoWebUrl(null)).toBeNull()
    expect(repoWebUrl(undefined)).toBeNull()
    expect(repoWebUrl('')).toBeNull()
    expect(repoWebUrl('javascript:alert(1)')).toBeNull()
  })
})

describe('splitPullRequestRefs', () => {
  it('links a trailing squash-merge reference', () => {
    expect(
      splitPullRequestRefs('Show only tagged releases (#173)', GH),
    ).toStrictEqual([
      { href: null, text: 'Show only tagged releases (' },
      { href: `${GH}/pull/173`, text: '#173' },
      { href: null, text: ')' },
    ])
  })

  it('links a merge-commit reference', () => {
    expect(
      splitPullRequestRefs('Merge pull request #82 from feature/x', GH),
    ).toStrictEqual([
      { href: null, text: 'Merge pull request ' },
      { href: `${GH}/pull/82`, text: '#82' },
      { href: null, text: ' from feature/x' },
    ])
  })

  it('links every reference in the subject', () => {
    const segments = splitPullRequestRefs('Revert #10, reland #11', GH)
    expect(segments.filter((s) => s.href)).toStrictEqual([
      { href: `${GH}/pull/10`, text: '#10' },
      { href: `${GH}/pull/11`, text: '#11' },
    ])
  })

  it('leaves the subject plain when there is no repo', () => {
    expect(splitPullRequestRefs('Bump version (#173)', null)).toStrictEqual([
      { href: null, text: 'Bump version (#173)' },
    ])
  })

  it('leaves subjects without references alone', () => {
    expect(splitPullRequestRefs('Bump version to 2.20.0', GH)).toStrictEqual([
      { href: null, text: 'Bump version to 2.20.0' },
    ])
  })

  it('ignores mid-word and non-numeric hashes', () => {
    expect(splitPullRequestRefs('fix sha#12 and #abc', GH)).toStrictEqual([
      { href: null, text: 'fix sha#12 and #abc' },
    ])
  })
})

describe('pullRequestRefs', () => {
  it('collects deduplicated references in message order', () => {
    expect(
      pullRequestRefs('Revert #10 (#10) then #11', `${GH}/commit/a`),
    ).toStrictEqual([
      { href: `${GH}/pull/10`, label: '#10' },
      { href: `${GH}/pull/11`, label: '#11' },
    ])
  })

  it('returns nothing without a commit URL to anchor on', () => {
    expect(pullRequestRefs('Add a thing (#5)', null)).toStrictEqual([])
  })
})
