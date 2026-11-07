{{/* Chart name. */}}
{{- define "APP_NAME.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Fully qualified name. Release named like the chart (helm install APP_NAME ...) gives
plain "APP_NAME", the same names as the Kustomize template.
*/}}
{{- define "APP_NAME.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "APP_NAME.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Selector labels. Explicit and minimal: selectors are immutable, so never add labels
here that may change between releases.
*/}}
{{- define "APP_NAME.selectorLabels" -}}
app.kubernetes.io/name: {{ include "APP_NAME.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "APP_NAME.labels" -}}
helm.sh/chart: {{ include "APP_NAME.chart" . }}
{{ include "APP_NAME.selectorLabels" . }}
app.kubernetes.io/version: {{ include "APP_NAME.imageTag" . | trunc 63 | trimSuffix "-" | quote }}
app.kubernetes.io/component: web
app.kubernetes.io/part-of: {{ include "APP_NAME.name" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "APP_NAME.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "APP_NAME.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "APP_NAME.imageTag" -}}
{{- default .Chart.AppVersion .Values.image.tag }}
{{- end }}

{{/* repository:tag, or repository@digest when a digest is pinned. */}}
{{- define "APP_NAME.image" -}}
{{- if .Values.image.digest }}
{{- printf "%s@%s" .Values.image.repository .Values.image.digest }}
{{- else }}
{{- printf "%s:%s" .Values.image.repository (include "APP_NAME.imageTag" .) }}
{{- end }}
{{- end }}

{{/* A PDB on a single replica blocks every node drain: render it only with >1. */}}
{{- define "APP_NAME.pdbEnabled" -}}
{{- if and .Values.podDisruptionBudget.enabled (or .Values.autoscaling.enabled (gt (int .Values.replicaCount) 1)) }}true{{- end }}
{{- end }}
