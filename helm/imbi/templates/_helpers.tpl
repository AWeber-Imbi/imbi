{{- define "imbi.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "imbi.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "imbi.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "imbi.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "imbi.selectorLabels" -}}
app.kubernetes.io/name: {{ include "imbi.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "imbi.secretName" -}}
{{- if .Values.existingSecret }}
{{- .Values.existingSecret }}
{{- else }}
{{- include "imbi.fullname" . }}
{{- end }}
{{- end }}

{{- define "imbi.clickhouseUrl" -}}
{{- required "externalClickhouse.url is required (point it at your ClickHouse instance)" .Values.externalClickhouse.url }}
{{- end }}

{{- define "imbi.containerPort" -}}
{{- if eq .Values.service.mode "api" }}8000
{{- else if eq .Values.service.mode "mcp" }}8001
{{- else if eq .Values.service.mode "assistant" }}8002
{{- else if eq .Values.service.mode "gateway" }}8003
{{- else if eq .Values.service.mode "slackbot" }}8004
{{- else if eq .Values.service.mode "scheduler" }}8005
{{- else }}8080
{{- end }}
{{- end }}

{{/*
The path imbi-api answers its status route on.

imbi-api mounts every router -- the status route included -- under the path
component of its public URL, so a deployment serving the API at
https://imbi.example.com/api answers /api/status and nothing at /status. The
probe has to follow it. In "all" mode the request goes through the bundled
Caddy, which preserves the path when forwarding to imbi-api, so the same
derived path applies.

imbi-scheduler and imbi-slackbot deliberately leave /status unprefixed and do
not use this.
*/}}
{{- define "imbi.apiStatusPath" -}}
{{- $prefix := "" }}
{{- if .Values.service.publicApiUrl }}
{{- $prefix = (urlParse .Values.service.publicApiUrl).path | trimSuffix "/" }}
{{- end }}
{{- printf "%s/status" $prefix }}
{{- end }}

{{- define "imbi.postgresUrl" -}}
{{- required "externalPostgresql.url is required (point it at your CloudNativePG / AGE-enabled PostgreSQL)" .Values.externalPostgresql.url }}
{{- end }}
