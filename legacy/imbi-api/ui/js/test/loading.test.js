import React from "react";
import {render} from "@testing-library/react";
import "@testing-library/jest-dom/extend-expect";

import Loading from '../components/Loading';


describe('loading',()=>{

    it("should render correctly",()=>{
        const {container} = render(<Loading/>)
        const wrapper = container.getElementsByClassName('loading')

        expect(wrapper).toHaveLength(1)
    })

    it("span should have class 'fas fa-spinner fa-spin'",()=>{
        const {container} = render(<Loading/>)
        const span = container.querySelector('span')
        expect(span).toHaveClass('fas fa-spinner fa-spin')
    })

    it("loading should render 'h1'",()=>{
        const {container} = render(<Loading/>)
        const heading = container.querySelectorAll('h1')

        expect(heading).toHaveLength(1)
    })
})
