{{/* Names. */}}
{{- define "n8n.name" -}}
{{- .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* A release named like "n8n" or "n8n-prod" is used as is: n8n-main, n8n-worker. */}}
{{- define "n8n.fullname" -}}
{{- if contains "n8n" .Release.Name -}}
{{- .Release.Name | trunc 50 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 50 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{/* Selector labels; call with (dict "root" $ "component" "main"). */}}
{{- define "n8n.selectorLabels" -}}
app.kubernetes.io/name: {{ include "n8n.name" .root }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/* Labels shared by every n8n pod, used by the data-store NetworkPolicy. */}}
{{- define "n8n.podLabels" -}}
app.kubernetes.io/part-of: {{ include "n8n.fullname" . }}
{{- end -}}

{{- define "n8n.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
app.kubernetes.io/version: {{ .Values.image.tag | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{ include "n8n.podLabels" . }}
{{- end -}}

{{- define "n8n.image" -}}
{{ printf "%s:%s" .Values.image.repository .Values.image.tag }}
{{- end -}}

{{/* Bull keys are <prefix>:<queue>:<type>; n8n's queue name is "jobs". */}}
{{- define "n8n.bullKey" -}}
{{- printf "%s:jobs:%s" .root.Values.queue.bullPrefix .type -}}
{{- end -}}

{{/*
Worker shutdown window. n8n force-exits N8N_GRACEFUL_SHUTDOWN_TIMEOUT seconds
after SIGTERM, so that is the longest execution plus a buffer. The kubelet's
grace period also covers the preStop hook, which runs before SIGTERM.
*/}}
{{- define "n8n.workerShutdownSeconds" -}}
{{- add .Values.executions.maxExecutionSeconds .Values.worker.shutdownBufferSeconds -}}
{{- end -}}

{{- define "n8n.workerGracePeriod" -}}
{{- add (include "n8n.workerShutdownSeconds" . | int) .Values.worker.preStopSleepSeconds 15 -}}
{{- end -}}

{{/*
SecretProviderClass spec. Rendered here so each Deployment can carry its
checksum: the mapping is read only at mount time.
*/}}
{{- define "n8n.spcSpec" -}}
provider: aws
parameters:
  region: {{ .Values.aws.region | quote }}
  usePodIdentity: "true"
  objects: |
    - objectName: {{ .Values.secrets.encryptionKey.secretName | quote }}
      objectType: "secretsmanager"
      objectAlias: {{ .Values.secrets.encryptionKey.alias | quote }}
    - objectName: {{ .Values.secrets.db.secretName | quote }}
      objectType: "secretsmanager"
      objectAlias: "db-credentials"
      jmesPath:
        - path: "username"
          objectAlias: {{ .Values.secrets.db.keys.username | quote }}
        - path: "password"
          objectAlias: {{ .Values.secrets.db.keys.password | quote }}
    - objectName: {{ .Values.secrets.redisAuth.secretName | quote }}
      objectType: "secretsmanager"
      objectAlias: {{ .Values.secrets.redisAuth.alias | quote }}
{{- end -}}

{{/*
Environment shared by main, webhook and worker. Secrets are *_FILE paths into
the CSI mount: n8n's config loader reads <VAR>_FILE for any variable it knows
(@n8n/config decorators.js in the image), so no value is ever in the pod spec.
*/}}
{{- define "n8n.sharedEnv" -}}
{{- $m := .Values.secrets.mountPath -}}
- name: EXECUTIONS_MODE
  value: "queue"
- name: N8N_ENCRYPTION_KEY_FILE
  value: {{ printf "%s/%s" $m .Values.secrets.encryptionKey.alias | quote }}
- name: DB_TYPE
  value: "postgresdb"
- name: DB_POSTGRESDB_HOST
  value: {{ .Values.database.host | quote }}
- name: DB_POSTGRESDB_PORT
  value: {{ .Values.database.port | quote }}
- name: DB_POSTGRESDB_DATABASE
  value: {{ .Values.database.name | quote }}
- name: DB_POSTGRESDB_SCHEMA
  value: {{ .Values.database.schema | quote }}
- name: DB_POSTGRESDB_USER_FILE
  value: {{ printf "%s/%s" $m .Values.secrets.db.keys.username | quote }}
- name: DB_POSTGRESDB_PASSWORD_FILE
  value: {{ printf "%s/%s" $m .Values.secrets.db.keys.password | quote }}
- name: DB_POSTGRESDB_SSL_ENABLED
  value: {{ .Values.database.ssl | quote }}
- name: DB_POSTGRESDB_POOL_SIZE
  value: {{ .Values.database.poolSize | quote }}
- name: QUEUE_BULL_PREFIX
  value: {{ .Values.queue.bullPrefix | quote }}
- name: QUEUE_BULL_REDIS_HOST
  value: {{ .Values.redis.host | quote }}
- name: QUEUE_BULL_REDIS_PORT
  value: {{ .Values.redis.port | quote }}
- name: QUEUE_BULL_REDIS_DB
  value: {{ .Values.redis.db | quote }}
- name: QUEUE_BULL_REDIS_TLS
  value: {{ .Values.redis.tls | quote }}
- name: QUEUE_BULL_REDIS_PASSWORD_FILE
  value: {{ printf "%s/%s" $m .Values.secrets.redisAuth.alias | quote }}
- name: N8N_WEBHOOK_URL
  value: {{ .Values.publicUrl | quote }}
- name: N8N_EDITOR_BASE_URL
  value: {{ .Values.publicUrl | quote }}
- name: N8N_PROXY_HOPS
  value: {{ .Values.proxyHops | quote }}
- name: EXECUTIONS_TIMEOUT
  value: {{ .Values.executions.maxExecutionSeconds | quote }}
- name: EXECUTIONS_TIMEOUT_MAX
  value: {{ .Values.executions.maxExecutionSeconds | quote }}
- name: EXECUTIONS_DATA_PRUNE
  value: {{ .Values.executions.prune | quote }}
- name: EXECUTIONS_DATA_MAX_AGE
  value: {{ .Values.executions.pruneMaxAgeHours | quote }}
- name: EXECUTIONS_DATA_PRUNE_MAX_COUNT
  value: {{ .Values.executions.pruneMaxCount | quote }}
- name: N8N_METRICS
  value: {{ .Values.metrics | quote }}
- name: GENERIC_TIMEZONE
  value: {{ .Values.timezone | quote }}
- name: N8N_DIAGNOSTICS_ENABLED
  value: "false"
# Editor "test workflow" runs go to the queue too, so main stays small and
# every execution shows up in the queue depth KEDA scales on.
- name: OFFLOAD_MANUAL_EXECUTIONS_TO_WORKERS
  value: "true"
{{- end -}}

{{- define "n8n.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: {{ .Values.podSecurity.runAsUser }}
runAsGroup: {{ .Values.podSecurity.runAsGroup }}
fsGroup: {{ .Values.podSecurity.fsGroup }}
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{- define "n8n.containerSecurityContext" -}}
runAsNonRoot: true
runAsUser: {{ .Values.podSecurity.runAsUser }}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
privileged: false
capabilities:
  drop:
    - ALL
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{/*
Writable paths on a read-only root filesystem. Found by running the image
with --read-only: n8n writes its settings file under /home/node/.n8n, compiles
static assets into /home/node/.cache at start, and the task runner uses /tmp.
*/}}
{{- define "n8n.writableMounts" -}}
- name: secrets-store
  mountPath: {{ .Values.secrets.mountPath }}
  readOnly: true
- name: n8n-home
  mountPath: /home/node/.n8n
- name: n8n-cache
  mountPath: /home/node/.cache
- name: tmp
  mountPath: /tmp
{{- end -}}

{{- define "n8n.volumes" -}}
- name: secrets-store
  csi:
    driver: secrets-store.csi.k8s.io
    readOnly: true
    volumeAttributes:
      secretProviderClass: {{ include "n8n.fullname" . }}
# Memory-backed: n8n copies the encryption key into .n8n/config.
- name: n8n-home
  emptyDir:
    medium: Memory
    sizeLimit: 64Mi
- name: n8n-cache
  emptyDir:
    sizeLimit: 256Mi
- name: tmp
  emptyDir:
    sizeLimit: 256Mi
{{- end -}}

{{/* Probes: /healthz is liveness, /healthz/readiness needs DB connected and migrated. */}}
{{- define "n8n.probes" -}}
startupProbe:
  httpGet:
    path: /healthz
    port: http
  periodSeconds: 5
  failureThreshold: {{ .startupFailureThreshold | default 24 }}
readinessProbe:
  httpGet:
    path: /healthz/readiness
    port: http
  periodSeconds: 10
  timeoutSeconds: 3
  failureThreshold: 3
livenessProbe:
  httpGet:
    path: /healthz
    port: http
  periodSeconds: 20
  timeoutSeconds: 3
  failureThreshold: 3
{{- end -}}
