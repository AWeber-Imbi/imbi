image := "ghcr.io/aweber-imbi/imbi"

[doc("Build the Docker image")]
[group("Build")]
build tag="latest":
    docker build -t {{ image }}:{{ tag }} .

[doc("Build and tag as both version and latest")]
[group("Build")]
release tag:
    docker build -t {{ image }}:{{ tag }} -t {{ image }}:latest .

[doc("Update all submodules to the latest commit on their tracking branch")]
[group("Submodules")]
update-submodules:
    git submodule update --remote --merge

[doc("Update all submodules to a specific tag")]
[group("Submodules")]
update-submodules-tag tag:
    #!/usr/bin/env sh
    set -e
    for module in imbi-api imbi-assistant imbi-common imbi-gateway imbi-mcp imbi-ui; do
        echo "Updating $module to {{ tag }}..."
        git -C "$module" fetch --tags
        git -C "$module" checkout "{{ tag }}"
    done
    echo "All submodules updated to {{ tag }}"
    echo "Run 'git add -A && git commit' to record the update"

[doc("Show the current version of each submodule")]
[group("Submodules")]
submodule-status:
    git submodule status

[doc("Build the documentation")]
[group("Docs")]
docs:
    docker run --rm -v {{ justfile_directory() }}/docs:/docs squidfunk/mkdocs-material build

[doc("Serve documentation locally for development")]
[group("Docs")]
docs-serve:
    docker run --rm -p 8088:8000 -v {{ justfile_directory() }}/docs:/docs squidfunk/mkdocs-material

[doc("Remove build artifacts")]
[group("Build")]
clean:
    rm -rf docs/site
