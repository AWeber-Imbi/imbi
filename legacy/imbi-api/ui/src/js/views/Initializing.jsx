import React from 'react'

import { Loading } from '../components'

export function Initializing() {
  return (
    <main className="flex flex-row flex-grow">
      <Loading caption="common.initializing" />
    </main>
  )
}
