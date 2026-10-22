{{- define "iir.name" -}}
intel-inference-router
{{- end }}

{{- define "iir.labels" -}}
app.kubernetes.io/name: {{ include "iir.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "iir.llama-deployment" -}}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: llama-{{ .name }}
  labels:
    app: llama-{{ .name }}
    lane: {{ .lane }}
    {{- include "iir.labels" .context | nindent 4 }}
spec:
  replicas: {{ .replicas }}
  selector:
    matchLabels:
      app: llama-{{ .name }}
  template:
    metadata:
      labels:
        app: llama-{{ .name }}
        lane: {{ .lane }}
    spec:
      {{- if .context.Values.topologySpread.enabled }}
      topologySpreadConstraints:
      - maxSkew: {{ .context.Values.topologySpread.maxSkew }}
        topologyKey: {{ .context.Values.topologySpread.topologyKey }}
        whenUnsatisfiable: ScheduleAnyway
        labelSelector:
          matchLabels:
            app: llama-{{ .name }}
      {{- end }}
      containers:
      - name: llama
        image: {{ .image }}
        args:
        - "--model"
        - {{ .ggufPath | quote }}
        - "--host"
        - "0.0.0.0"
        - "--port"
        - "8080"
        - "--ctx-size"
        - {{ .ctxSize | quote }}
        - "--threads"
        - {{ .threads | quote }}
        - "--parallel"
        - {{ .parallel | quote }}
        {{- if .cpuStrict }}
        - "--cpu-strict"
        - "1"
        {{- end }}
        - "--alias"
        - {{ .alias | quote }}
        ports:
        - containerPort: 8080
        resources:
          {{- toYaml .resources | nindent 10 }}
        volumeMounts:
        - name: models
          mountPath: /models
      volumes:
      - name: models
        persistentVolumeClaim:
          claimName: {{ .context.Values.storage.pvcName }}
---
apiVersion: v1
kind: Service
metadata:
  name: llama-{{ .name }}
  labels:
    {{- include "iir.labels" .context | nindent 4 }}
spec:
  selector:
    app: llama-{{ .name }}
  ports:
  - port: 8080
    targetPort: 8080
{{- end }}
