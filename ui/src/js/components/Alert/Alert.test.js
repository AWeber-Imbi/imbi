import React from "react"
import {render} from "@testing-library/react"
import "@testing-library/jest-dom/extend-expect"

import Alert from "./Alert"

describe("Alert", () => {
  it("should render an alert with info attributes", () => {
    const tree = render(<Alert level="info">Info</Alert>)
    expect(tree).toMatchSnapshot()
  })
  it("should render an alert with warning attributes", () => {
    const tree = render(<Alert level="warning">Warning</Alert>)
    expect(tree).toMatchSnapshot()
  })
  it("should render an alert with error attributes", () => {
    const tree = render(<Alert level="error">Error</Alert>)
    expect(tree).toMatchSnapshot()
  })
  it("should render an alert with success attributes", () => {
    const tree = render(<Alert level="success">Success</Alert>)
    expect(tree).toMatchSnapshot()
  })
  it("should render an alert with an object for a child", () => {
    const tree = render(<Alert level="info"><span>Foo</span></Alert>)
    expect(tree).toMatchSnapshot()
  })
})
