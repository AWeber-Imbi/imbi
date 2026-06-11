// Deployments per environment requested by a user-triggered project
// resync. The API caps this at 100 (the GitHub per-page ceiling); a deep
// resync both backfills missing historical DeploymentEvent rows and
// re-resolves performed_by on already-stored events (dedup'd by
// external_run_id), which is how stale deploy attribution gets corrected.
export const DEEP_RESYNC_LIMIT = 100
