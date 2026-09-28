/* eslint-disable react-refresh/only-export-components */
import { createContext, type ReactNode, useContext } from 'react'

/**
 * The GitHub web root of the project being viewed, so markdown rendered
 * anywhere under a project page can link its ``#N`` references without
 * threading the URL through every card. Null outside a project page, or
 * when the project has no known repository.
 */
const ProjectRepoContext = createContext<null | string>(null)

export function ProjectRepoProvider({
  children,
  repoUrl,
}: {
  children: ReactNode
  repoUrl: null | string
}) {
  return (
    <ProjectRepoContext.Provider value={repoUrl}>
      {children}
    </ProjectRepoContext.Provider>
  )
}

export function useProjectRepoUrl(): null | string {
  return useContext(ProjectRepoContext)
}
