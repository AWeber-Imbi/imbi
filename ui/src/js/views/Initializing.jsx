import React from 'react'

import { Loading } from '../components'

export function Initializing() {
  return (
    <main className="flex flex-row flex-grow font-sans">
      <Loading caption="common.initializing" />
    </main>
  )
}
