import React from "react";
import {render} from "@testing-library/react";
import "@testing-library/jest-dom/extend-expect";

import CRUDIndex from "../components/CRUDIndex";

const RenderCRUD = () => {
  return (
    <CRUDIndex
      breadcrumbItems={[
        { title: "Admin" },
        {
          title: "Admin",
          path: "home/admin"
        }
      ]}
      columns={[1, 3, 4, 5]}
      data={["element1", "element2"]}
      errorMessage="Error"
      keyField="1"
      successMessage="Success"
      title="title"
      deleteCallback={() => {}}
      updateCallback={() => {}}
      validationCallback={() => {}}
    />
  );
};

describe("CRUDIndex", () => {
  it("should render CRUDindex", () => {
    const { container } = render(<RenderCRUD />);
    const node = container.getElementsByClassName("container-fluid");
    expect(node).toHaveLength(1);
  });
  it("should render table", () => {
    const { container } = render(<RenderCRUD />);
    const CRUDtable = container.getElementsByClassName("table");
    expect(CRUDtable).toHaveLength(2);
  });
  it("should render toolbar", () => {
    const { container } = render(<RenderCRUD />);
    const CRUDtoolbar = container.getElementsByClassName("toolbar");
    expect(CRUDtoolbar).toHaveLength(1);
  });
  it("should render div with class responsive table", () => {
    const { container } = render(<RenderCRUD />);
    const CRUDresponsive = container.getElementsByClassName("table-responsive");
    expect(CRUDresponsive).toHaveLength(1);
  });
});
