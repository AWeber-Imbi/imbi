#!/bin/sh
set -e
FILENAME=${1:-ddl.sql}
REVISION=$(git rev-parse HEAD | cut -b 1-7)

matches() {
    input="$1"
    pattern="$2"
    echo "$input" | grep -q "$pattern"
}


echo "Building ${FILENAME} @ ${REVISION}"

# Build the DDL from the MANIFEST file
echo "-- Auto-constructed DDL file from version ${REVISION}" > ${FILENAME}
echo "" >> ${FILENAME}
while IFS='\n' read -r LINE || [ -n "${LINE}" ]; do
  if matches "${LINE}" "\.sql"
  then
    printf "\n\n-- ${LINE}\n\n" >> ${FILENAME}
    cat ${LINE} >> ${FILENAME}
  fi
done <MANIFEST
