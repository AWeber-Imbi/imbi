import React from "react";
import {render} from "@testing-library/react";
import "@testing-library/jest-dom/extend-expect";

import Alert from "../components/Alert";

describe("Alert", () => {
  it("should render Alert success", () => {
    const { getAllByText } = render(<Alert color="success">Success</Alert>);
    const node = getAllByText("Success");
    expect(node).toHaveLength(1);
  });
  it("should render Alert Error", () => {
    const { getAllByText } = render(<Alert color="error">Error</Alert>);
    const nodeError = getAllByText("Error");
    expect(nodeError).toHaveLength(1);
  });
});
