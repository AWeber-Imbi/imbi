import React, {useState} from "react";
import {render} from "@testing-library/react";
import "@testing-library/jest-dom/extend-expect";
import uuidv4 from "uuid/v4";
import "regenerator-runtime/runtime";

import {Panel, Wizard} from "../components";
import AddAutomations from "../views/project/AddAutomations";
import AddDetails from "../views/project/AddDetails";
import AddDependencies from "../views/project/AddDependencies";
import AddFinish from "../views/project/AddFinish";
import AddLinks from "../views/project/AddLinks";

const RenderWizard = () => {
  const metadata = {
    configuration_systems: [],
    cookie_cutters: [],
    data_centers: [],
    deployment_types: [],
    environments: [],
    gitlab_url: "https://gitlab.com",
    ldap_enabled: true,
    project_link_types:[],
    teams:[],
    project_types:[],
    orchestration_systems:[]
  };
  const [project, setProject] = useState({
    id: uuidv4(),
    name: null,
    slug: null,
    description: null,
    owned_by: null,
    project_type: null,
    data_center: null,
    configuration_system: null,
    deployment_type: null,
    orchestration_system: null
  })
  const automations = {
    gitlab_url: null,
    grafana_cookie_cutter: null,
    repository_cookie_cutter: null,
    setup_in_sentry: true
  }
  const erred = false
  const dependencies = []
  const links = []

  const finishProgress = [
    { iconClass: "iconClass", text: "text", error: "errorMessage" }
  ];
  const breadcrumbs = [
    {
      title: "Projects",
      path: "/projects/"
    },
    {
      title: "Add Project",
      path: "/project/add"
    }
  ];

  function setProjectCallback(values) {
    setProject(values);
  }

  return (
    <Panel breadcrumbs={breadcrumbs}>
      <Wizard
        isDone={() => {}}
        title="wizard"
        erred={erred}
        onDoneClick={() => {}}
        onErredClick={() => {}}
        onFinishClick={() => {}}
      >
        <AddDetails
          data={project}
          metadata={metadata}
          setDataCallback={setProjectCallback}
          title="Step 1: Details"
        />
        <AddAutomations
          data={[]}
          metadata={metadata}
          project={project}
          setDataCallback={() => {}}
          title="Step 2: Automations"
        />
        <AddDependencies
          data={dependencies}
          metadata={metadata}
          setDataCallback={() => {}}
          title="Step 3: Dependencies"
        />
        <AddLinks
          automations={automations}
          data={links}
          metadata={metadata}
          setDataCallback={() => {}}
          title="Step 4: Links"
        />
        <AddFinish
          automations={automations}
          dependencies={dependencies}
          links={links}
          metadata={metadata}
          progress={finishProgress}
          project={project}
          title="Step 5: Finish"
        />
      </Wizard>
    </Panel>
  );
};

describe("Wizard", () => {
  it("should render", () => {
    const { container } = render(<RenderWizard />);
    const node = container.querySelector("div");

    expect(node).toHaveClass("container-fluid");
  });

  it("should render topbar", () => {
    const { container } = render(<RenderWizard />);
    const nodeTopbar = container.getElementsByClassName("topbar");

    expect(nodeTopbar).toHaveLength(1);
  });

  it("should render wizard", () => {
    const { container } = render(<RenderWizard />);
    const nodeWizard = container.getElementsByClassName("wizard");

    expect(nodeWizard).toHaveLength(1);
  });

  it("should render nav-tabs", () => {
    const { container } = render(<RenderWizard />);
    const nodeTabs = container.getElementsByClassName("nav-tabs");

    expect(nodeTabs).toHaveLength(1);
  });

  it("should render tab-content", () => {
    const { container } = render(<RenderWizard />);
    const nodeTabs = container.getElementsByClassName("tab-content");

    expect(nodeTabs).toHaveLength(1);
  });

});
