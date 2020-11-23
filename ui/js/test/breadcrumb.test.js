import React from "react";
import {render} from "@testing-library/react";
import "@testing-library/jest-dom/extend-expect";

import Breadcrumb from "../components/Breadcrumb";

describe("Breadcrumb", () => {
  it("should render breadcrumb", () => {
    const { container } = render(<Breadcrumb />);
    const node = container.querySelectorAll("nav");
    expect(node).toHaveLength(1);
  });

  it("should render ol with class 'breadcrumb'", () => {
    const { container } = render(<Breadcrumb />);
    const ol = container.getElementsByClassName("breadcrumb");
    expect(ol.length).toBe(1);
  });

  it("should render list items", () => {
    const { container } = render(<Breadcrumb />);
    const listItems = container.getElementsByClassName("breadcrumb-item");
    expect(listItems.length).toBe(1);
  });
});
