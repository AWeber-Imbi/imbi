import React from "react"
import {render} from "@testing-library/react"
import {configure, shallow} from "enzyme"
import "@testing-library/jest-dom/extend-expect"
import Adapter from "enzyme-adapter-react-16"

import Tooltip from "./Tooltip"

configure({adapter: new Adapter()})

describe("Tooltip", () => {
  it("should render the hidden tooltip Tooltip", () => {
    const tree = render(
      <Tooltip value="Tooltip">
        <div id="child">Foo</div>
      </Tooltip>)
    expect(tree).toMatchSnapshot()
  })

  it("should change the visibility on mouse over/out", () => {
    const element = shallow(
      <Tooltip value="Tooltip">
        <div id="child">Foo</div>
      </Tooltip>)

    let divs = element.find("div")
    expect(divs.at(2).hasClass("hidden")).toBe(true)
    expect(divs.at(2).hasClass("visible")).toBe(false)
    divs.at(0).simulate("mouseover")
    element.rerender()
    divs = element.find("div")
    expect(divs.at(2).hasClass("hidden")).toBe(false)
    expect(divs.at(2).hasClass("visible")).toBe(true)
    divs.at(0).simulate("mouseout")
    element.rerender()
    divs = element.find("div")
    expect(divs.at(2).hasClass("hidden")).toBe(true)
    expect(divs.at(2).hasClass("visible")).toBe(false)
  })
})
