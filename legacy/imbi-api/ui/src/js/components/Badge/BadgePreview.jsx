import React, { Fragment } from 'react'

import { Documentation } from '../'

import { Badge } from './Badge'

function BadgePreview() {
  return (
    <Documentation
      title="Badges"
      urlPath="/ui/components/badges"
      code={`\
<Badge color="blue">Blue</Badge>
<Badge color="dark">Dark</Badge>
<Badge color="gray">Gray</Badge>
<Badge color="green">Green</Badge>
<Badge color="indigo">Indigo</Badge>
<Badge color="pink">Pink</Badge>
<Badge color="purple">Purple</Badge>
<Badge color="red">Red</Badge>
<Badge color="yellow">Yellow</Badge>`}
      preview={
        <Fragment>
          <Badge color="blue">Blue</Badge>
          <Badge color="dark">Dark</Badge>
          <Badge color="gray">Gray</Badge>
          <Badge color="green">Green</Badge>
          <Badge color="indigo">Indigo</Badge>
          <Badge color="pink">Pink</Badge>
          <Badge color="purple">Purple</Badge>
          <Badge color="red">Red</Badge>
          <Badge color="yellow">Yellow</Badge>
        </Fragment>
      }
      properties={`\
- \`color\` - The badge color. One of \`blue\`, \`dark\`, \`gray\`, \`green\`, \`indigo\`, \`pink\`, \`purple\`, \`red\`, or \`yellow\`.
- \`href\` - The href attribute specifies the URL of the page the link goes to.
- \`target\` - The target attribute specifies where to open the linked document.
`}
    />
  )
}
export { BadgePreview }
