export default {
  en: {
    translation: {
      common: {
        loading: 'Initializing',
        name: 'Name',
        description: 'Description',
        slug: 'Slug',
        iconClass: 'Icon Class',
        id: 'ID',
        edit: 'Edit',
        delete: 'Delete',
        cancel: 'Cancel',
        save: 'Save',
        saving: 'Saving ...',
        slugDescription:
          'A slug is the part of a URL which identifies a particular page on a website in an easy to read form.',
        textClass: 'Text Class',
        welcome: 'Welcome',
        required: 'Required Field',
        group: 'Group'
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
        configurationSystems: {
          collectionName: 'Configuration Systems',
          itemName: 'Configuration System',
          errors: {
            uniqueViolation:
              'A configuration system with the same name already exists'
          }
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
        dataCenters: {
          collectionName: 'Data Centers',
          itemName: 'Data Center',
          errors: {
            uniqueViolation: 'A data center with the same name already exists'
          }
        },
        deploymentTypes: {
          collectionName: 'Deployment Types',
          itemName: 'Deployment Type',
          errors: {
            uniqueViolation:
              'A deployment type with the same name already exists'
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
        orchestrationSystems: {
          collectionName: 'Orchestration Systems',
          itemName: 'Orchestration System',
          errors: {
            uniqueViolation:
              'An orchestration system with the same name already exists'
          }
        },
        projectFactTypes: {
          collectionName: 'Project Fact Types',
          itemName: 'Project Fact Type',
          projectType: 'Project Type',
          factType: 'Fact Type',
          weight: 'Weight',
          weightDescription:
            'The weight from 0 to 100 against the total score for a project. Total weight should across all types for a project type should not exceed 100.',
          errors: {
            uniqueViolation:
              'A project fact type with the same name already exists'
          }
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
        title: 'Dashboard'
      },
      operationsLog: {
        addEntry: 'Add Entry',
        title: 'Operations Log'
      },
      operationsLogNewEntry: {
        title: 'Add Operations Log Entry'
      },
      project: {
        name: 'Name',
        namespace: 'Namespace',
        selectNamespace: 'Select a Namespace',
        projectType: 'Project Type',
        dataCenter: 'Data Center',
        environments: 'Environments',
        configurationSystem: 'Configuration System',
        deploymentType: 'Deployment Type',
        orchestrationSystem: 'Orchestration System'
      },
      projects: {
        newProject: 'New Project',
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
        }
      }
    }
  }
}
