#!/bin/sh -e

echo "Installing utilities"
apk --update add curl-dev gcc git libffi-dev make musl-dev tzdata

# upgrade pip to make sure that we get the most modern wheel selection alg
pip install --upgrade pip setuptools wheel

echo "Creating directories"
mkdir -p /tmp/test/build
ls -lR /tmp/test

cd /tmp/test
echo "Copying files from /source to $(pwd)"
tar c -C /source -f - \
    .gitignore \
    .pre-commit-config.yaml \
    LICENSE \
    MANIFEST.in \
    Makefile \
    VERSION \
    bootstrap \
    compose.yml \
    ddl \
    imbi \
    scaffolding \
    setup.cfg \
    setup.py \
    tests \
  | tar xf -

cat > .env <<EOF
export DEBUG=1
EOF
ls -al

echo "Configuring git"
git init --quiet
git config user.email 'ci@aweber.io'
git config user.name 'Imbi CI'
git branch -M main
git add .
git commit -m 'fake'

echo "Running tests in $(pwd)"
make test
