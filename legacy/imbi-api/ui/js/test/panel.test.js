import React from "react";
import {render} from "@testing-library/react";
import "@testing-library/jest-dom/extend-expect";

import Panel from "../components/Panel";

describe("Panel", () => {
  it("should render correctly", () => {
    const { container } = render(<Panel />);

    const outerWrapper = container.querySelector("div");
    expect(outerWrapper).toHaveClass("container-fluid");
  });

  it("should render a div with class 'topbar'", () => {
    const { container } = render(<Panel />);

    const topbar = container.getElementsByClassName("topbar");
    expect(topbar).toHaveLength(1);
  });

  it("should render a 'breadcrumb'", () => {
    const { container } = render(<Panel />);
    const breadcrumb = container.getElementsByClassName("breadcrumb");
    expect(breadcrumb).toHaveLength(1);
  });
});
