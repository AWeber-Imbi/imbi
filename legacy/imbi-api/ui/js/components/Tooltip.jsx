import React, { useState } from "react";

import { Tooltip } from "reactstrap";

export default function(props) {
  const [isOpen, setIsOpen] = useState(false);
  return (
    <Tooltip
      {...props}
      autohide={false}
      isOpen={isOpen}
      delay={0}
      toggle={() => {
        setIsOpen(!isOpen);
      }}
      data-testid="tooltip-display"
    >
      {props.children}
    </Tooltip>
  );
}
