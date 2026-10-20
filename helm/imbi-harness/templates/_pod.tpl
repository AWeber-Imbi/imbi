{{/*
The runner pod of plan section 6.1 and ADR 0022: two containers, three
users, no shared process namespace, per-container credential volumes.
The Deployment and the ScaledJob share it; "job" is true for a Job pod.
*/}}

{{- define "imbi-harness.securityContext" -}}
# Uid 0 with only SETUID and SETGID; each process drops to its own user
# at start (plan section 2 rule 4).
runAsUser: 0
runAsNonRoot: false
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
  add: ["SETUID", "SETGID"]
{{- end }}

{{- define "imbi-harness.executor" -}}
- name: executor
  image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
  imagePullPolicy: {{ .Values.image.pullPolicy }}
  {{- if eq .Values.pool.mode "scaledJob" }}
  # A native sidecar (Kubernetes 1.29+): it stops when the runner exits,
  # so the Job completes.
  restartPolicy: Always
  {{- end }}
  args: ["executor"]
  env:
    - name: IMBI_API_URL
      value: {{ .Values.imbi.apiUrl | quote }}
  securityContext:
    {{- include "imbi-harness.securityContext" . | nindent 4 }}
  resources:
    {{- toYaml .Values.resources.executor | nindent 4 }}
  volumeMounts:
    - {name: work, mountPath: /work}
    - {name: executor-socket, mountPath: /run/executor}
    - {name: executor-credentials, mountPath: /run/creds}
{{- end }}

{{- define "imbi-harness.podSpec" -}}
{{- $job := eq .Values.pool.mode "scaledJob" -}}
serviceAccountName: {{ include "imbi-harness.pool" . }}
automountServiceAccountToken: false
enableServiceLinks: false
shareProcessNamespace: false
terminationGracePeriodSeconds: {{ .Values.terminationGracePeriodSeconds }}
{{- if $job }}
restartPolicy: Never
{{- end }}
securityContext:
  seccompProfile:
    type: RuntimeDefault
  # No fsGroup: it would give a group access to the credential volumes.
{{- if $job }}
initContainers:
  {{- include "imbi-harness.executor" . | nindent 2 }}
{{- end }}
containers:
  - name: runner
    image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
    imagePullPolicy: {{ .Values.image.pullPolicy }}
    args: ["runner"]
    env:
      - name: IMBI_API_URL
        value: {{ required "imbi.apiUrl is required" .Values.imbi.apiUrl | quote }}
      - name: IMBI_HARNESS_POOL
        value: {{ include "imbi-harness.pool" . | quote }}
      {{- with .Values.imbi.model }}
      - name: IMBI_HARNESS_MODEL
        value: {{ . | quote }}
      {{- end }}
      {{- with .Values.imbi.mcpUrl }}
      - name: IMBI_HARNESS_MCP_URL
        value: {{ . | quote }}
      {{- end }}
      {{- if .Values.extraCaCerts.configMap }}
      - name: IMBI_HARNESS_EXTRA_CA
        value: /etc/imbi-harness/ca/{{ .Values.extraCaCerts.key }}
      {{- end }}
      {{- if $job }}
      # A Job: exit after the chain; the ScaledJob starts the next one.
      - name: IMBI_HARNESS_END_OF_CHAIN
        value: exit
      - name: IMBI_HARNESS_IDLE_EXIT_SECONDS
        value: {{ .Values.scaledJob.idleExitSeconds | quote }}
      {{- else }}
      # The runner deletes its own pod at the end of its chain.
      - name: POD_NAME
        valueFrom:
          fieldRef: {fieldPath: metadata.name}
      - name: POD_NAMESPACE
        valueFrom:
          fieldRef: {fieldPath: metadata.namespace}
      {{- end }}
    securityContext:
      {{- include "imbi-harness.securityContext" . | nindent 6 }}
    resources:
      {{- toYaml .Values.resources.runner | nindent 6 }}
    volumeMounts:
      - {name: work, mountPath: /work}
      - {name: executor-socket, mountPath: /run/executor}
      - {name: runner-credentials, mountPath: /run/creds}
      - {name: pool, mountPath: /var/run/secrets/imbi/pool, readOnly: true}
      {{- if .Values.extraCaCerts.configMap }}
      - {name: extra-ca, mountPath: /etc/imbi-harness/ca, readOnly: true}
      {{- end }}
      {{- if not $job }}
      - name: service-account-token
        mountPath: /var/run/secrets/kubernetes.io/serviceaccount
        readOnly: true
      {{- end }}
  {{- if not $job }}
  {{- include "imbi-harness.executor" . | nindent 2 }}
  {{- end }}
volumes:
  {{- if .Values.extraCaCerts.configMap }}
  - name: extra-ca
    configMap:
      name: {{ .Values.extraCaCerts.configMap | quote }}
  {{- end }}
  - name: work
    emptyDir:
      sizeLimit: {{ .Values.work.sizeLimit }}
  - name: executor-socket
    emptyDir: {medium: Memory}
  - name: runner-credentials
    emptyDir: {medium: Memory}
  - name: executor-credentials
    emptyDir: {medium: Memory}
  # Owned by uid 0, mode 0400: only the runner's uid 0 reads them.
  - name: pool
    secret:
      secretName: {{ include "imbi-harness.secretName" . }}
      defaultMode: 0400
  {{- if not $job }}
  # Only to delete its own pod; a Job pod exits instead.
  - name: service-account-token
    projected:
      defaultMode: 0400
      sources:
        - serviceAccountToken: {path: token, expirationSeconds: 3600}
        # The cluster CA is public: the runner reads it as runner.
        - configMap:
            name: kube-root-ca.crt
            items:
              - {key: ca.crt, path: ca.crt, mode: 0444}
  {{- end }}
{{- with .Values.nodeSelector }}
nodeSelector:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.tolerations }}
tolerations:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.affinity }}
affinity:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- end }}
