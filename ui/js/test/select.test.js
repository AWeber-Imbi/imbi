import React from "react";
import { render, fireEvent, cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/extend-expect";

import { Select } from "../components/Form";

const techCompanies = [
  { label: "Apple", value: 1 },
  { label: "Facebook", value: 2 },
  { label: "Netflix", value: 3 },
  { label: "Tesla", value: 4 },
  { label: "Amazon", value: 5 },
  { label: "Alphabet", value: 6 }
];

const SelectMenu = () => {
  return (
    <Select
      id="testid"
      name="select"
      options={techCompanies}
      placeholder="Select Item"
      required={true}
    />
  );
};

describe("Select", () => {
  it("should render correctly", () => {
    const { container } = render(<SelectMenu />);
    const select = container.querySelectorAll("select");
    expect(select).toHaveLength(1);
  });

  it("should capture change", () => {
    const { getByText, container } = render(<SelectMenu />);
    const node = container.querySelector("select");

    fireEvent.change(node, { target: { value: "Apple" } });
    expect(getByText("Apple")).toBeInTheDocument();
  });
  afterEach(cleanup);
});
