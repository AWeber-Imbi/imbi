export default {
  en: {
    translation: {
      common: {
        loading: "Initializing",
        name: "Name",
        description: "Description",
        slug: "Slug",
        iconClass: "Icon Class",
        edit: "Edit",
        delete: "Delete",
        cancel: "Cancel",
        save: "Save",
        welcome: "Welcome"
      },
      error: {
        title: "ERROR",
        notFound: "Not Found"
      },
      headerNavItems: {
        administration: "Administration",
        dashboard: "Dashboard",
        projects: "Projects",
        changeLog: "Change Log",
        newChangeLogEntry: "New Change Log Entry",
        newProject: "New Project",
        openNewMenu: "Open New Menu",
        openUserMenu: "Open User Menu",
        profile: "Profile",
        settings: "Settings",
        signOut: "Sign Out",
        userMenu: "User Menu"
      },
      footer: {
        apiDocumentation: "API Documentation"
      },
      login: {
        username: "User Name",
        password: "Password",
        signIn: "Sign in"
      },

      admin: {
        title: "Administration",
        crud: {
          itemAdded: "{{keyValue}} was successfully added to {{collectionName}}",
          newAction: "New {{itemName}}"
        },
        sidebar: {
          settings: "Settings",
          userManagement: "User Management"
        },
        configurationSystems: {
          collectionName: "Configuration Systems",
          itemName: "Configuration System",
          errors: {
            uniqueViolation: "A configuration system with the same name already exists"
          }
        },
        cookieCutters: {
          collectionName: "Cookie Cutters",
          itemName: "Cookie Cutter",
          type: "Type",
          url: "Git URL",
          urlDescription: "The Git URL to the cookie cutter",
          errors: {
            uniqueViolation: "A cookie cutter with the same name already exists"
          }
        },
        projectTypes: {
          collectionName: "Project Types",
          itemName: "Project Type",
          slugDescription: "A slug is the part of a URL which identifies a particular page on a website in an easy to read form.",
          errors: {
            uniqueViolation: "A project type with the same name already exists"
          }
        }
      },
      user: {
        profile: {
          title: "{{displayName}}'s Profile",
          displayName: "Display Name",
          userName: "User Name",
          userType: "User Type",
          externalId: "External ID",
          emailAddress: "Email Address",
          groups: "Groups"
        }
      },

      add: {
        step1: "Step 1: Details",
        step2: "Step 2: Automations",
        step3: "Step 3: Dependencies",
        step4: "Step 4: Links",
        step5: "Step 5: Finish",
      },
      addAutomation: {
        message:
          "The following automation tasks are available on new project setup:",
        createProject: "Create Project in Sentry",
        createGitlab: "Create GitLab Project",
        repositoryCookie: "Repository Cookie Cutter",
        grafanaCookie: "Grafana Cookie Cutter",
        placeholder: "Select Cookie Cutter",
      },
      addDependencies: {
        team: "Team",
        dataCenter: "Data Center",
        project: "Project",
        message:
          "Select other projects that are immediate dependencies of this project:",
        noProject: "No projects defined",
      },
      addDetails: {
        message:
          "The project name should uniquely identify the project within the team but can be duplicated across teams.",
        projectName: "Project Name",
        ownedBy: "Owned By",
        selectTeam: "Select Team",
        projectType: "Project Type",
        selectProjectType: "Select Project Type",
        dataCenter: "Data Center",
        selectDataCenter: "Select Data Center",
        configurationSystem: "Configuration System",
        selectConfigurationSystem: "Select Configuration System",
        deploymentType: "Deployment Type",
        selectDeploymentType: "Select Deployment Type",
        orchestrationSystem: "Orchestration System",
        selectOrchestrationSystem: "Select Orchestration System",
      },
      addFinish: {
        message:
          "Adding the project and performing automation actions:",
        error: "ERROR",
        projectOverview: "Project Overview",
        name: "Name",
        slug: "Slug",
        description: "Description",
        ownedBy: "Owned By",
        projectType: "Project Type",
        dataCenter: "Data Center",
        configurationSystem: "Configuartion System",
        deploymentType: "Deployment Type",
        orchestrationSystem: "Orchestration System",
        automations: "Automations",
        setupSentry: "Setup Project in Sentry",
        setupGitlab: "Setup Project in GitLab",
        repoCookieCutter: "Repository Cookie Cutter:",
        grafanaCookie: "Grafana Cookie Cutter:",
        dependencies: "Dependencies",
        noDependencies: "No dependencies specified",
        noLinks: "No links specified",
        links: "Links",
      },
      addLinks: {
        message: "Add links to the project that will show up in the project inventory and on the project details page:",
        selectLinkType: "Select Link Type",
        linkType: "Link Type",
        linkURL: "Link URL",
        url: "URL",
        noSerice: "No Project Links",
        addFirstLink: "Use the inline form above to add the first link.",
      },
      inventory: {
        name: "Name",
        projects: "Projects",
        dataCenter: "Data Center",
        team: "Team",
        projectType: "Project Type",
        project: "Project",
        edit: "Edit",
      },
      dataCenter: {
        dataCenter: "Data Center",
        dataCenters: "Data Centers",
        iconClass: "Icon Class",
        message: "The Data Center you entered already exists",
      },
      deploymentType: {
        title: "Deployment Type",
        titles: "Deployment Types",
        iconClass: "Icon Class",
        message: "The Deployment Type you entered already exists",
      },
      environment: {
        title: "Environment Type",
        titles: "Environment Types",
        iconClass: "Icon Class",
        message: "The Environment you entered already exists",
      },
      groups: {
        name: "Group Name",
        internal: "internal",
        ldap: "ldap",
        groupType: "Group Type",
        errorHelp:
          "External ID is required when Group Type is LDAP, otherwise it must be empty",
        externalId: "External ID",
        permissions: "Permissions",
        message: "The Group you entered already exists",
        title: "Group",
        titles: "Groups",
        iconClass: "Icon Class",
      }
    }
  }
}
