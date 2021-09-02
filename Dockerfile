FROM python:3.9-alpine3.12

ARG VERSION=0.0.0

ENV PORT=8000

COPY api/dist/imbi-${VERSION}.tar.gz /tmp/
COPY api/docker-config.yaml /etc/imbi/imbi.yaml

RUN apk add --no-cache --virtual install-deps cargo curl-dev gcc libffi-dev libressl-dev linux-headers musl-dev postgresql-dev rust \
 && apk add --no-cache libcurl libpq \
 && pip3 install --no-cache-dir /tmp/imbi-${VERSION}.tar.gz \
 && apk del --purge install-deps \
 && rm /tmp/imbi-${VERSION}.tar.gz

EXPOSE 8000

CMD /usr/local/bin/imbi /etc/imbi/imbi.yaml
