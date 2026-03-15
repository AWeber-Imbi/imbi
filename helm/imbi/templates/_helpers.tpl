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

{{- define "imbi.neo4jUrl" -}}
{{- if .Values.neo4j.enabled }}
{{- printf "bolt://%s:7687" .Release.Name }}
{{- else }}
{{- .Values.externalNeo4j.url }}
{{- end }}
{{- end }}

{{- define "imbi.clickhouseUrl" -}}
{{- if .Values.clickhouse.enabled }}
{{- printf "http://%s:%s@%s-clickhouse:8123/imbi" .Values.clickhouse.auth.username .Values.clickhouse.auth.password .Release.Name }}
{{- else }}
{{- .Values.externalClickhouse.url }}
{{- end }}
{{- end }}

{{- define "imbi.containerPort" -}}
{{- if eq .Values.service.mode "api" }}8000
{{- else if eq .Values.service.mode "mcp" }}8001
{{- else if eq .Values.service.mode "assistant" }}8002
{{- else if eq .Values.service.mode "gateway" }}8003
{{- else }}8080
{{- end }}
{{- end }}

{{- define "imbi.postgresUrl" -}}
{{- if .Values.postgresql.enabled }}
{{- printf "postgresql://postgres:%s@%s-postgresql/%s" .Values.postgresql.auth.postgresPassword .Release.Name .Values.postgresql.auth.database }}
{{- else }}
{{- .Values.externalPostgresql.url }}
{{- end }}
{{- end }}
