{{/* Names. */}}
{{- define "keyvault-csi-demo.name" -}}
{{- .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "keyvault-csi-demo.fullname" -}}
{{- if contains .Chart.Name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "keyvault-csi-demo.selectorLabels" -}}
app.kubernetes.io/name: {{ include "keyvault-csi-demo.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "keyvault-csi-demo.labels" -}}
{{ include "keyvault-csi-demo.selectorLabels" . }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/* The SA name is fixed by the federated identity credential's subject, so it is never derived from the release. */}}
{{- define "keyvault-csi-demo.serviceAccountName" -}}
{{- .Values.serviceAccount.name -}}
{{- end -}}

{{/* File names (aliases) the app must find under the mount. */}}
{{- define "keyvault-csi-demo.requiredFiles" -}}
{{- $aliases := list -}}
{{- range .Values.keyVault.objects -}}
{{- $aliases = append $aliases .objectAlias -}}
{{- end -}}
{{- join "," $aliases -}}
{{- end -}}

{{/*
SecretProviderClass spec. Rendered once here so the Deployment can carry its
checksum: the object mapping is read only when the volume is mounted, so a
change to it needs new pods. A rotated secret *value* does not (the CSI
driver's secret_rotation_enabled polls and rewrites the files in place).
*/}}
{{- define "keyvault-csi-demo.spcSpec" -}}
provider: azure
parameters:
  usePodIdentity: "false"
  useVMManagedIdentity: "false"
  # Workload identity: the pod's ServiceAccount carries the
  # azure.workload.identity/client-id annotation (serviceaccount.yaml) and
  # this clientID must match it exactly -- the driver exchanges the
  # projected SA token for this client's Entra token via the federated
  # credential, never a client secret.
  clientID: {{ .Values.serviceAccount.azureClientId | quote }}
  keyvaultName: {{ .Values.keyVault.vaultUrl | trimPrefix "https://" | trimSuffix ".vault.azure.net/" | quote }}
  tenantId: {{ .Values.keyVault.tenantId | quote }}
  objects: |
    array:
      {{- range .Values.keyVault.objects }}
      - |
        objectName: {{ .objectName }}
        objectType: {{ .objectType }}
        objectAlias: {{ .objectAlias }}
      {{- end }}
{{- end -}}

{{- define "keyvault-csi-demo.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: 10001
runAsGroup: 10001
fsGroup: 10001
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{- define "keyvault-csi-demo.containerSecurityContext" -}}
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
