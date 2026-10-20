{{- define "pharmacy-service.name" -}}
pharmacy-{{ .Values.workload }}
{{- end -}}

{{- define "pharmacy-service.labels" -}}
app.kubernetes.io/name: {{ include "pharmacy-service.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/part-of: gcp-ai-pharmacy-platform
workload: {{ .Values.workload }}
{{- end -}}

{{- define "pharmacy-service.selectorLabels" -}}
app.kubernetes.io/name: {{ include "pharmacy-service.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
