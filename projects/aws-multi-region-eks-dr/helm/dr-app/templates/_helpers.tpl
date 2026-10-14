{{/* Chart name and release-scoped names. */}}
{{- define "dr-app.name" -}}
{{- .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "dr-app.fullname" -}}
{{- if contains .Chart.Name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "dr-app.labels" -}}
app.kubernetes.io/name: {{ include "dr-app.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{ include "dr-app.commonLabels" . }}
{{- end -}}

{{/* Labels without name/instance, for pod templates that add selector labels. */}}
{{- define "dr-app.commonLabels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
dr.example.com/region: {{ .Values.region }}
dr.example.com/region-role: {{ .Values.regionRole }}
{{- end -}}

{{/* Selector labels; component is "api" or "worker". */}}
{{- define "dr-app.selectorLabels" -}}
app.kubernetes.io/name: {{ include "dr-app.name" .root }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "dr-app.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- .Values.serviceAccount.name | default (include "dr-app.fullname" .) -}}
{{- else -}}
{{- .Values.serviceAccount.name | default "default" -}}
{{- end -}}
{{- end -}}

{{/* Pod-level security context shared by every workload. */}}
{{- define "dr-app.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: 10001
runAsGroup: 10001
fsGroup: 10001
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{/* Container-level security context shared by every container. */}}
{{- define "dr-app.containerSecurityContext" -}}
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

{{/* Spread across zones (the ask) and, softly, across nodes. */}}
{{- define "dr-app.topologySpread" -}}
- maxSkew: 1
  topologyKey: topology.kubernetes.io/zone
  whenUnsatisfiable: {{ .root.Values.topologySpread.whenUnsatisfiable }}
  labelSelector:
    matchLabels:
      {{- include "dr-app.selectorLabels" . | nindent 6 }}
- maxSkew: 1
  topologyKey: kubernetes.io/hostname
  whenUnsatisfiable: ScheduleAnyway
  labelSelector:
    matchLabels:
      {{- include "dr-app.selectorLabels" . | nindent 6 }}
{{- end -}}

{{/* Workers run only when enabled; the failover CLI flips this per region. */}}
{{- define "dr-app.workerReplicas" -}}
{{- if .Values.workers.enabled -}}{{ .Values.workers.replicas }}{{- else -}}0{{- end -}}
{{- end -}}
