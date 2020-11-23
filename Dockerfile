FROM python:3.8-alpine3.12

ARG VERSION=0.1.0

ENV PORT=8000

COPY dist/imbi-${VERSION}.tar.gz /tmp/

RUN apk add --no-cache --virtual install-deps curl-dev gcc libffi-dev libressl-dev linux-headers musl-dev postgresql-dev \
 && apk add --no-cache libcurl libpq \
 && pip3 install --no-cache-dir /tmp/imbi-${VERSION}.tar.gz \
 && apk del --purge install-deps \
 && rm /tmp/imbi-${VERSION}.tar.gz

EXPOSE 8000

CMD imbi
