# 10. Automations

Date: 2021-06-28

## Status

Draft

## Context

Automations are simply pieces of code that are invoked when an action is taken
in the UI.  They are meant to automate some amount of manual labor.  For
example, the first automation that was added creates a repository in GitLab
when a project is created in Imbi.  The automation is fired from the UI when
the user enables the "Create project in gitlab" option when creating a new
project.

The GitLab repository creation automation requires some information to do
what it does:

* GitLab group that the project will be created in
* Path within the group to create the project
* Which project link should be updated with the repo path

The GitLab group is tied to the Imbi namespace that the user created the
project under.  Since the Imbi namespace is flat, the SCM path is formed by
concatenating a prefix based on the project type to the GitLab group.  For
example, creating a new "HTTP API" in the "Operations" Imbi namespace might
result in the project being created in `.../OPS/applications/apis`.  The
GitLab group is determined by the Imbi namespace so "Operations" needs to be
configured to map to the SCM prefix of "/OPS".  Similarly, "HTTP API"
project types are always placed in the "/applications/api" folder.

The project link is a little different since it is up to the user to create
a generic "GitLab SCM" link type if one is desired.  Even if one exists, it
might make sense to not automatically populate it.  This is only one type of
"well-known identfier" that an automation may need to know.  Since they are
not necessarily tied to existing database tables or concepts, it makes sense
for them to be configured manually.

> In general, if an automation needs to add data to Imbi that is not a core
> data value, then the automation should be configured with the necessary
> information instead of guessing.

## Decision

### SCM path calcuations

The SCM path is simply the prefix configured on the Imbi namespace followed
by the suffix configured for the Imbi project type.

### Well-known Imbi Identifiers

I decided to add a sub-tree to the configuration file named `automations` at
the root.  The immediate child is the name of the automation that is being
configured with the entire sub-tree being controlled by the automation.  The
*current* implementation of the GitLab project creation automation uses this
to know whether it should add a project link for the SCM location or not.

## Consequences

* The Imbi namespace portion of the SCM path allows for different groups to
  be rooted in different parts of the SCM namespace
* The Imbi project type portion of the SCM path ensures that different groups
  use the same internal structure for different project types
* Separating the SCM path into two components provides flexibility for a
  variety of SCM layouts while maintaining a decent amount of consistency
* Using explicit configuration in automations for "well-known identifiers"
  removes some of the magic of discovering them or the headaches around
  having automations modify the database/data elements.
