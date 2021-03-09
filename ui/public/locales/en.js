export default {
  en: {
    translation: {
      common: {
        all: 'All',
        initializing: 'Initializing',
        loading: 'Loading',
        name: 'Name',
        description: 'Description',
        slug: 'Slug',
        icon: 'Icon',
        iconClass: 'Icon Class',
        id: 'ID',
        edit: 'Edit',
        delete: 'Delete',
        done: 'Done',
        cancel: 'Cancel',
        close: 'Close',
        save: 'Save',
        saving: 'Saving ...',
        on: 'On',
        off: 'Off',
        turnOn: 'Turn On',
        turnOff: 'Turn Off',
        slugDescription:
          'A slug is the part of a URL which identifies a particular page on a website in an easy to read form.',
        textClass: 'Text Class',
        welcome: 'Welcome',
        required: 'Required Field',
        group: 'Group',
        invalidURL: 'Value does not appear to be a URL',
        paginatorPosition:
          'Showing {{startRecord}} to {{endRecord}} of {{totalRecords}} {{noun}}',
        pageSize: 'Page Size',
        previous: 'Previous',
        next: 'Next',
        value: 'Value',
        filter: 'Filter'
      },
      terms: {
        description: 'Description',
        name: 'Name',
        namespace: 'Namespace',
        projectType: 'Project Type',
        dataCenter: 'Data Center',
        deploymentType: 'Deployment Type',
        healthScore: 'Health Score',
        links: 'Links',
        record: 'record',
        records: 'records',
        reports: 'Reports',
        score: 'Score'
      },
      error: {
        title: 'ERROR',
        accessDenied: 'Access Denied',
        notFound: 'Not Found'
      },
      headerNavItems: {
        administration: 'Administration',
        dashboard: 'Dashboard',
        newOperationsLogEntry: 'Add Ops Log Entry',
        newProject: 'Create a New Project',
        openNewMenu: 'Open New Menu',
        openUserMenu: 'Open User Menu',
        profile: 'Profile',
        settings: 'Settings',
        signOut: 'Sign Out',
        userMenu: 'User Menu'
      },
      footer: {
        apiDocumentation: 'API Documentation'
      },
      admin: {
        title: 'Administration',
        crud: {
          deleteConfirmation: {
            title: 'Delete {{itemName}}?',
            text:
              'Are you sure you would like to delete "{{value}}" from the available {{collectionName}}?',
            button: 'Delete'
          },
          itemAdded:
            '"{{value}}" was successfully added to the available {{collectionName}}',
          itemDeleted:
            '"{{value}}" was successfully deleted from the available {{collectionName}}',
          itemUpdated:
            '"{{value}}" was successfully updated in the available {{collectionName}}',
          newTitle: 'New {{itemName}}',
          savingTitle: 'Saving {{itemName}}',
          updateTitle: 'Edit {{itemName}}'
        },
        sidebar: {
          settings: 'Settings',
          userManagement: 'User Management'
        },
        cookieCutters: {
          collectionName: 'Cookie Cutters',
          itemName: 'Cookie Cutter',
          type: 'Type',
          url: 'Git URL',
          urlDescription: 'The Git URL to the cookie cutter',
          errors: {
            uniqueViolation: 'A cookie cutter with the same name already exists'
          }
        },
        environments: {
          collectionName: 'Environments',
          itemName: 'Environment',
          errors: {
            uniqueViolation: 'An environment with the same name already exists'
          }
        },
        namespaces: {
          collectionName: 'Namespaces',
          itemName: 'Namespace',
          maintainedBy: 'Managed By',
          maintainedByDescription:
            'Groups that have access to manage projects in this namespace',
          errors: {
            uniqueViolation: 'A namespace with the same name already exists'
          }
        },
        projectFactTypes: {
          collectionName: 'Project Fact Types',
          itemName: 'Project Fact Type',
          projectType: 'Project Type',
          factType: 'Fact Type',
          dataType: 'Data Type',
          weight: 'Weight',
          weightDescription:
            'The weight from 0 to 100 against the total score for a project. Total weight should across all types for a project type should not exceed 100.',
          uiOptions: 'Display Options',
          errors: {
            uniqueViolation:
              'A project fact type with the same name already exists'
          }
        },
        projectFactTypeEnums: {
          collectionName: 'Fact Type Enums',
          itemName: 'Fact Type Enum Value',
          scoreDescription:
            'The score for this value, with a maximum value of 100'
        },
        projectFactTypeRanges: {
          collectionName: 'Fact Type Ranges',
          itemName: 'Fact Type Range',
          minValue: 'Minimum Value',
          maxValue: 'Maximum Value',
          scoreDescription:
            'The score for this value, with a maximum value of 100'
        },
        projectLinkTypes: {
          linkType: 'Link Type',
          collectionName: 'Project Link Types',
          itemName: 'Project Link Type',
          errors: {
            uniqueViolation:
              'A project link type with the same name already exists'
          }
        },
        projectTypes: {
          collectionName: 'Project Types',
          itemName: 'Project Type',
          pluralName: 'Pluralized Name',
          environmentURLs: 'Per-Environment URLs',
          errors: {
            uniqueViolation: 'A project type with the same name already exists'
          }
        }
      },
      login: {
        username: 'User Name',
        password: 'Password',
        signIn: 'Sign in'
      },
      dashboard: {
        title: 'Dashboard',
        projectTypes: 'Projects by Type'
      },
      operationsLog: {
        addEntry: 'Add Entry',
        title: 'Operations Log'
      },
      operationsLogNewEntry: {
        title: 'Add Operations Log Entry'
      },
      project: {
        projectAttributes: 'Project Attributes',
        attributes: 'Attributes',
        projectLinks: 'Project Links',
        links: 'Links',
        projectAutomations: 'Project Automations',
        automations: 'Automations',
        projectDependencies: 'Project Dependencies',
        dependencies: 'Dependencies',
        name: 'Name',
        namespace: 'Namespace',
        selectNamespace: 'Select a Namespace',
        projectType: 'Project Type',
        environments: 'Environments',
        descriptionDescription:
          'Provide a high-level purpose and context for the project',
        createGitLabRepository: 'Create GitLab Repository',
        createSentryProject: 'Create Project in Sentry',
        dashboardCookieCutter: 'Dashboard Cookie Cutter',
        projectCookieCutter: 'Project Cookie Cutter',
        savingProject: 'Saving Project',
        projectSaved: 'Project Saved',
        savingLinks: 'Saving Links',
        linksSaved: 'Links Saved',
        savingDependencies: 'Saving Dependencies',
        dependenciesSaved: 'Dependencies Saved',
        projectURLs: 'Per-Environment URLs',
        specifyEnvironments:
          'Environments are required to enter per-environment URLs',
        savingURLs: 'Saving Per-Environment URLs',
        urls: 'URLs',
        urlsSaved: 'Per-Environment URLs saved'
      },
      projects: {
        newProject: 'New Project',
        project: 'project',
        projects: 'projects',
        paginationState:
          'Showing {{startRecord}} to {{endRecord}} of {{totalRecords}} {{noun}}',
        title: 'Projects'
      },
      user: {
        profile: {
          title: "{{displayName}}'s Profile",
          displayName: 'Display Name',
          userName: 'User Name',
          userType: 'User Type',
          externalId: 'External ID',
          emailAddress: 'Email Address',
          groups: 'Groups'
        },
        settings: {
          title: 'User Settings',
          authenticationTokens: {
            title: 'Authentication Tokens',
            buttonText: 'Generate New Token',
            createdAt: 'Created On',
            expiresAt: 'Expires On',
            lastUsedAt: 'Last Used',
            generate: 'Generate Token',
            generated: 'Token Generated',
            generatedWarning:
              '<p>Make sure to copy your new authentication token.</p><p>You won&rsquo;t be able to see it again!</p>',
            generating: 'Generating Token',
            description:
              'Authentication Tokens are used to access Imbi&rsquo;s <a href="/api-docs" target="_new">API</a>.',
            unused: 'Unused'
          }
        }
      }
    }
  }
}
