{{/* Names. */}}
{{- define "secure-frontend.name" -}}
{{- .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "secure-frontend.fullname" -}}
{{- if contains .Chart.Name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "secure-frontend.selectorLabels" -}}
app.kubernetes.io/name: {{ include "secure-frontend.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "secure-frontend.labels" -}}
{{ include "secure-frontend.selectorLabels" . }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/* The SA name is fixed by the Pod Identity association, so it is never derived from the release. */}}
{{- define "secure-frontend.serviceAccountName" -}}
{{- .Values.serviceAccount.name -}}
{{- end -}}

{{/* File names the app must find under the mount: the jmesPath aliases plus the API key. */}}
{{- define "secure-frontend.requiredFiles" -}}
{{- $k := .Values.secrets.db.keys -}}
{{- join "," (list $k.username $k.password $k.host .Values.secrets.apiKey.alias) -}}
{{- end -}}

{{/*
SecretProviderClass spec. Rendered once here so the Deployment can carry its
checksum: the mapping is read only when the volume is mounted, so a change to
it needs new pods. A change to a secret *value* does not (rotation, see
docs/architecture.md).
*/}}
{{- define "secure-frontend.spcSpec" -}}
provider: aws
parameters:
  region: {{ .Values.aws.region | quote }}
  usePodIdentity: {{ .Values.aws.usePodIdentity | toString | quote }}
  objects: |
    - objectName: {{ .Values.secrets.db.secretName | quote }}
      objectType: "secretsmanager"
      objectAlias: {{ .Values.secrets.db.alias | quote }}
      jmesPath:
        - path: "username"
          objectAlias: {{ .Values.secrets.db.keys.username | quote }}
        - path: "password"
          objectAlias: {{ .Values.secrets.db.keys.password | quote }}
        - path: "host"
          objectAlias: {{ .Values.secrets.db.keys.host | quote }}
    - objectName: {{ .Values.secrets.apiKey.secretName | quote }}
      objectType: "secretsmanager"
      objectAlias: {{ .Values.secrets.apiKey.alias | quote }}
{{- if .Values.secrets.sync.enabled }}
# Copies the mounted values into a Kubernetes Secret (etcd). Only for consumers
# that need env vars; this chart's app never reads it.
secretObjects:
  - secretName: {{ .Values.secrets.sync.secretName }}
    type: Opaque
    data:
      - objectName: {{ .Values.secrets.db.keys.username }}
        key: username
      - objectName: {{ .Values.secrets.db.keys.password }}
        key: password
      - objectName: {{ .Values.secrets.db.keys.host }}
        key: host
      - objectName: {{ .Values.secrets.apiKey.alias }}
        key: api-key
{{- end }}
{{- end -}}

{{- define "secure-frontend.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: 10001
runAsGroup: 10001
fsGroup: 10001
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{- define "secure-frontend.containerSecurityContext" -}}
runAsNonRoot: true
runAsUser: 10001
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
privileged: false
capabilities:
  drop:
    - ALL
seccompProfile:
  type: RuntimeDefault
{{- end -}}
