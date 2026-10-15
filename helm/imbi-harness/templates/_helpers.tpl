{{- define "imbi-harness.pool" -}}
{{- default .Release.Name .Values.pool.name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "imbi-harness.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "imbi-harness.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "imbi-harness.selectorLabels" -}}
app.kubernetes.io/name: imbi-harness
app.kubernetes.io/instance: {{ .Release.Name }}
imbi.aweber.com/pool: {{ include "imbi-harness.pool" . }}
{{- end }}

{{- define "imbi-harness.secretName" -}}
{{- default (printf "%s-pool" (include "imbi-harness.pool" .)) .Values.poolCredential.existingSecret }}
{{- end }}
