import { UserIdentity } from 'imbi-ui'

export const Sizes = () => (
  <div className="flex flex-col gap-4">
    <UserIdentity displayName="Dana Whitfield" email="dana.whitfield@aweber.com" size="small" />
    <UserIdentity displayName="Dana Whitfield" email="dana.whitfield@aweber.com" size="medium" />
    <UserIdentity
      displayName="Dana Whitfield"
      email="dana.whitfield@aweber.com"
      secondary="Platform Engineering"
      size="large"
    />
  </div>
)

export const Medium = () => (
  <UserIdentity displayName="Marcus Oyelaran" email="marcus.oyelaran@aweber.com" />
)

export const BotActor = () => (
  <div className="flex flex-col gap-3">
    <UserIdentity actor="github-actions[bot]" size="small" />
    <UserIdentity actor="dependabot[bot]" secondary="Automated dependency updates" size="medium" />
  </div>
)

export const NameResolution = () => (
  <div className="flex flex-col gap-3">
    <UserIdentity email="kevin.vance@aweber.com" size="small" />
    <UserIdentity actor="priya-n" size="small" />
    <UserIdentity size="small" />
  </div>
)

export const AvatarStack = () => (
  <div className="flex items-center gap-1">
    <UserIdentity displayName="Dana Whitfield" hideName size="medium" />
    <UserIdentity displayName="Marcus Oyelaran" hideName size="medium" />
    <UserIdentity displayName="Priya Natarajan" hideName size="medium" />
    <UserIdentity actor="github-actions[bot]" hideName size="medium" />
  </div>
)

export const DeployedBy = () => (
  <div className="min-w-0">
    <div className="text-tertiary mb-1.5 text-overline font-semibold uppercase">Deployed by</div>
    <UserIdentity actor="dwhitfield" displayName="Dana Whitfield" size="small" />
  </div>
)
