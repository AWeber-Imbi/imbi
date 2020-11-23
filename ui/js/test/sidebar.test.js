import React from "react";
import {render} from "@testing-library/react";
import "@testing-library/jest-dom/extend-expect";

import SideBar from "../components/SideBar";

describe("Sidebar", () => {
  it("should render correctly", () => {
    const { container } = render(<SideBar />);
    expect(container.children.length).toBe(1);
  });

  it("should render ul with class 'nav flex-column' ", () => {
    const { container } = render(<SideBar />);
    const sidbarWrapperUL = container.querySelector("ul");
    expect(sidbarWrapperUL).toHaveClass("nav flex-column");
  });

  it("should render div with class 'toggle-sidebar' ", () => {
    const { container } = render(<SideBar />);
    const sidbarWrapperToggle = container.getElementsByClassName(
      "toggle-sidebar"
    );
    expect(sidbarWrapperToggle).toHaveLength(1);
  });

  it("should render button with class 'btn btn-link'  ", () => {
    const { container } = render(<SideBar />);
    const toggleButton = container.getElementsByClassName("btn btn-link");

    expect(toggleButton).toHaveLength(1);
  });
});
