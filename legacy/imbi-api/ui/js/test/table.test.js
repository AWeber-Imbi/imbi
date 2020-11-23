import React from "react";
import {render} from "@testing-library/react";
import "@testing-library/jest-dom/extend-expect";

import {Table} from "../components/Table";

const columns = [{
    editable:true,
    name:"name",
    placeholder:"configure system name",
    required:true,
    sortable:true
}]

const data = []

const RenderTable = () => {
  return (
    <Table
      columns={columns}
      data={data}
      keyField="Name"
      sortColumn="Name"
      sortDirection="asc"
      deleteCallback={()=>{}}
      updateCallback={()=>{}}
      validationCallback={()=>{}}
    ></Table>
  );
};

describe('Table',()=>{
    it('should render table',()=>{
        const {container} = render(<RenderTable/>)
        const node = container.querySelectorAll('table')
        expect(node).toHaveLength(1)
    })

    it('should render table-responsive',()=>{
        const {container} = render(<RenderTable/>)
        const nodeTable = container.getElementsByClassName('table-responsive')
        expect(nodeTable).toHaveLength(1)
    })

    it('should render table-striped',()=>{
        const {container} = render(<RenderTable/>)
        const nodeTableStriped = container.getElementsByClassName('table-striped')
        expect(nodeTableStriped).toHaveLength(1)
    })

    it('should render thead',()=>{
        const {container} = render(<RenderTable/>)
        const nodeThead = container.querySelectorAll('thead')
        expect(nodeThead).toHaveLength(1)
    })

    it('should render tbody',()=>{
        const {container} = render(<RenderTable/>)
        const nodeTbody = container.querySelectorAll('tbody')
        expect(nodeTbody).toHaveLength(1)
    })
})
