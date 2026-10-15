{{- define "orders-api.name" -}}
{{- .Chart.Name -}}
{{- end -}}

{{- define "orders-api.fullname" -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "orders-api.selectorLabels" -}}
app.kubernetes.io/name: {{ include "orders-api.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "orders-api.labels" -}}
{{ include "orders-api.selectorLabels" . }}
app.kubernetes.io/version: {{ include "orders-api.tag" . | trunc 63 | quote }}
app.kubernetes.io/part-of: gitops-delivery-platform
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
example.com/environment: {{ .Values.env }}
{{- end -}}

{{/* Immutable tag required: a 40-char git SHA or semver plus a short SHA. Never latest. */}}
{{- define "orders-api.tag" -}}
{{- $tag := required "image.tag is required (set it in envs/<env>/values.yaml)" .Values.image.tag | toString -}}
{{- if not (regexMatch "^([0-9a-f]{40}|v?[0-9]+\\.[0-9]+\\.[0-9]+-[0-9a-f]{7,40})$" $tag) -}}
{{- fail (printf "image.tag %q is not immutable: use a 40-char git SHA or <semver>-<sha>" $tag) -}}
{{- end -}}
{{- $tag -}}
{{- end -}}

{{- define "orders-api.image" -}}
{{- printf "%s:%s" .Values.image.repository (include "orders-api.tag" .) -}}
{{- end -}}

{{- define "orders-api.workloadKind" -}}
{{- if .Values.rollout.enabled -}}Rollout{{- else -}}Deployment{{- end -}}
{{- end -}}

{{- define "orders-api.workloadAPIVersion" -}}
{{- if .Values.rollout.enabled -}}argoproj.io/v1alpha1{{- else -}}apps/v1{{- end -}}
{{- end -}}

{{/* Pod template shared by the Deployment and the Rollout. */}}
{{- define "orders-api.podTemplate" -}}
metadata:
  labels:
    {{- include "orders-api.labels" . | nindent 4 }}
  {{- with .Values.podAnnotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
spec:
  serviceAccountName: {{ include "orders-api.fullname" . }}
  automountServiceAccountToken: {{ .Values.serviceAccount.automountToken }}
  enableServiceLinks: false
  securityContext:
    runAsNonRoot: true
    runAsUser: 10001
    runAsGroup: 10001
    fsGroup: 10001
    seccompProfile:
      type: RuntimeDefault
  topologySpreadConstraints:
    - maxSkew: 1
      topologyKey: topology.kubernetes.io/zone
      whenUnsatisfiable: ScheduleAnyway
      labelSelector:
        matchLabels:
          {{- include "orders-api.selectorLabels" . | nindent 10 }}
  containers:
    - name: orders-api
      image: {{ include "orders-api.image" . }}
      imagePullPolicy: {{ .Values.image.pullPolicy }}
      ports:
        - name: http
          containerPort: {{ .Values.containerPort }}
          protocol: TCP
      env:
        - name: APP_ENV
          value: {{ .Values.env | quote }}
        - name: APP_VERSION
          value: {{ include "orders-api.tag" . | quote }}
        - name: PORT
          value: {{ .Values.containerPort | quote }}
      {{- if .Values.externalSecret.enabled }}
      envFrom:
        - secretRef:
            name: {{ .Values.externalSecret.targetName }}
      {{- end }}
      livenessProbe:
        httpGet:
          path: /healthz
          port: http
        periodSeconds: 10
        failureThreshold: 3
      readinessProbe:
        httpGet:
          path: /readyz
          port: http
        periodSeconds: 5
        failureThreshold: 3
      resources:
        {{- toYaml .Values.resources | nindent 8 }}
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        privileged: false
        capabilities:
          drop: ["ALL"]
      volumeMounts:
        - name: tmp
          mountPath: /tmp
  volumes:
    - name: tmp
      emptyDir:
        sizeLimit: 64Mi
  {{- with .Values.nodeSelector }}
  nodeSelector:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  {{- with .Values.tolerations }}
  tolerations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
{{- end -}}
