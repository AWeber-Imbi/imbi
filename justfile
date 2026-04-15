image := "ghcr.io/aweber-imbi/imbi"

[doc("Display the available commands")]
[default]
[group("Development")]
@help:
    just --list

[doc("Build the Docker image")]
[group("Build")]
build tag="latest":
    docker build -t {{ image }}:{{ tag }} .

[doc("Build and tag as both version and latest")]
[group("Build")]
release tag:
    docker build -t {{ image }}:{{ tag }} -t {{ image }}:latest .

[doc("Update all submodules to what is currently checked in")]
[group("Submodules")]
checkout-submodules:
    git submodule update --remote --checkout

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

[doc("Build and initialize docker environment")]
[group("Development")]
bootstrap:
    docker compose up --build --wait --detach
    docker compose exec imbi imbi-api setup
    ./runtime/manage-caddy annotate http://localhost:$(docker compose port imbi 2019 | cut -d: -f2)

[doc("Destroy docker environment and remove artifacts")]
[group("Development")]
teardown: clean
    docker compose down --remove-orphans --volumes
    rm -fr runtime/uv-cache/ runtime/wheels/*

start-dev service:
    #!/usr/bin/env sh
    set -eu
    if ! port_spec="$(docker compose port imbi 2019)" ; then
        docker compose up --wait --detach imbi
    fi
    docker compose build '{{service}}'
    docker compose up --scale '{{service}}=1' --detach --wait
    ./runtime/manage-caddy up "http://localhost:${port_spec#*:}/" "{{service}}"

stop-dev service:
    #!/usr/bin/env sh
    set -eu
    if ! port_spec="$(docker compose port imbi 2019)" ; then
        docker compose up --wait --detach imbi
    fi
    docker compose scale '{{service}}=0'
    ./runtime/manage-caddy down "http://localhost:${port_spec#*:}/" "{{service}}"
