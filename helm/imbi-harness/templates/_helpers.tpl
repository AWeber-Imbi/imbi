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

{{/* pool.mode, checked: a typo must not quietly render a Deployment. */}}
{{- define "imbi-harness.mode" -}}
{{- $mode := .Values.pool.mode -}}
{{- if not (has $mode (list "deployment" "scaledJob")) -}}
{{- fail (printf "pool.mode must be deployment or scaledJob, not %q" $mode) -}}
{{- end -}}
{{- $mode -}}
{{- end }}

{{- define "imbi-harness.secretName" -}}
{{- default (printf "%s-pool" (include "imbi-harness.pool" .)) .Values.poolCredential.existingSecret }}
{{- end }}

{{/* Every runner pod of the namespace: the subject of the egress policies. */}}
{{- define "imbi-harness.runnerPods" -}}
pods:
  namespaceSelector:
    matchLabels:
      kubernetes.io/metadata.name: {{ .Release.Namespace }}
  podSelector:
    matchLabels:
      app.kubernetes.io/name: imbi-harness
{{- end }}

{{/* The egress proxy pods: Deployment, Service, PDB, and policies. */}}
{{- define "imbi-harness.proxySelectorLabels" -}}
app.kubernetes.io/name: imbi-egress-proxy
{{- end }}

{{/* The egress proxy pods: the subject of the proxy policies. */}}
{{- define "imbi-harness.proxyPods" -}}
pods:
  namespaceSelector:
    matchLabels:
      kubernetes.io/metadata.name: {{ .Release.Namespace }}
  podSelector:
    matchLabels:
      {{- include "imbi-harness.proxySelectorLabels" . | nindent 6 }}
{{- end }}

{{/* The runners' egress proxy URL, with no user info. */}}
{{- define "imbi-harness.egressProxyUrl" -}}
{{- $p := .Values.egressProxy -}}
http://{{ default (printf "imbi-egress-proxy.%s.svc" .Release.Namespace) $p.host }}:{{ int $p.port }}
{{- end }}
