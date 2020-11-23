import React from "react";
import {render, cleanup} from "@testing-library/react";
import "@testing-library/jest-dom/extend-expect";

import Icon from "../components/Icon";

afterEach(cleanup);

describe("icon", () => {
  test("Renders correctly", () => {
    const { container } = render(<Icon className="fas" />);
    expect(container.children.length).toBe(1);
  });

  it("should render 'fas fa-filter' classname", () => {
    const { container } = render(<Icon className="fas fa-filter" />);
    expect(container.firstChild).toHaveClass("fas fa-filter");
  });
});
