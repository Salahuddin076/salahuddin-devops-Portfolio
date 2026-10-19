{{/* Names. */}}
{{- define "multiarch-app.name" -}}
{{- .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "multiarch-app.fullname" -}}
{{- if contains .Chart.Name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{/* Labels shared by every pool. Intentionally no "pool" key here: the
Service selects on these alone so it balances across the stable and canary
Deployments both. Each Deployment adds its own app.kubernetes.io/pool label
on top, for its own matchLabels/PDB/topology-spread scoping. */}}
{{- define "multiarch-app.selectorLabels" -}}
app.kubernetes.io/name: {{ include "multiarch-app.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "multiarch-app.labels" -}}
{{ include "multiarch-app.selectorLabels" . }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "multiarch-app.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "multiarch-app.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- required "serviceAccount.name is required when serviceAccount.create is false" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "multiarch-app.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: 10001
runAsGroup: 10001
fsGroup: 10001
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{- define "multiarch-app.containerSecurityContext" -}}
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

{{/* Node-affinity block for a given architecture string, honoring
.Values.affinity.preferred. Used identically by the stable and canary
Deployments so the only difference between the two pools is which
architecture they pass in. */}}
{{- define "multiarch-app.archAffinity" -}}
nodeAffinity:
{{- if .preferred }}
  preferredDuringSchedulingIgnoredDuringExecution:
    - weight: 100
      preference:
        matchExpressions:
          - key: kubernetes.io/arch
            operator: In
            values:
              - {{ .arch | quote }}
{{- else }}
  requiredDuringSchedulingIgnoredDuringExecution:
    nodeSelectorTerms:
      - matchExpressions:
          - key: kubernetes.io/arch
            operator: In
            values:
              - {{ .arch | quote }}
{{- end }}
{{- end -}}
