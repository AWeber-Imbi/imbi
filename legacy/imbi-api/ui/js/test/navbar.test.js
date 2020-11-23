import React from "react";
import {render, cleanup} from "@testing-library/react";
import "@testing-library/jest-dom/extend-expect";

import NavBar from "../components/NavBar";

afterEach(cleanup);

describe("NavBar", () => {
  test("Renders correctly", () => {
    const { container } = render(<NavBar />);
    expect(container.children.length).toBe(1);
  });

  it("should render 'header' tag", () => {
    const { container } = render(<NavBar />);
    const header = container.querySelectorAll("header");
    expect(header.length).toEqual(1);
  });

  it("should render 'nav' tag", () => {
    const { container } = render(<NavBar />);
    const nav = container.querySelectorAll("nav");
    expect(nav.length).toEqual(1);
  });

  it("should render 'ul' tag", () => {
    const { container } = render(<NavBar />);
    const unorderedlist = container.querySelectorAll("ul");
    expect(unorderedlist.length).toEqual(1);
  });

  it("should render 'Button with class dropdown-item'", () => {
    const { container } = render(<NavBar />);
    const buttonitem = container.querySelector("button");
    expect(buttonitem).toHaveClass("dropdown-item");
  });

  it("should render a div with classname of 'dropdown-menu dropdown-menu-right'", () => {
    const { container } = render(<NavBar />);
    const divider = container.querySelector("div");
    expect(divider).toHaveClass("dropdown-menu dropdown-menu-right");
  });
});
