{{- define "portable-service.name" -}}
portable-service
{{- end -}}

{{- define "portable-service.labels" -}}
app.kubernetes.io/name: {{ include "portable-service.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/part-of: multi-cloud-kubernetes
{{- end -}}

{{- define "portable-service.selectorLabels" -}}
app.kubernetes.io/name: {{ include "portable-service.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
