{{- define "nff-ticket-monitor.name" -}}
{{- .Chart.Name -}}
{{- end -}}

{{- define "nff-ticket-monitor.labels" -}}
app.kubernetes.io/name: {{ include "nff-ticket-monitor.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/*
Environment shared by both CronJobs. Kept in one place so the two jobs can
never drift apart on things like timezone or rate limiting.
*/}}
{{- define "nff-ticket-monitor.env" -}}
- name: TZ
  value: {{ .Values.timezone | quote }}
- name: STATE_DIR
  value: {{ .Values.storage.mountPath | quote }}
- name: TELEGRAM_BOT_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secret.name }}
      key: {{ .Values.secret.telegramTokenKey }}
- name: TELEGRAM_CHAT_ID
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secret.name }}
      key: {{ .Values.secret.telegramChatIdKey }}
- name: UPTIME_KUMA_PUSH_URL
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secret.name }}
      key: {{ .Values.secret.uptimeKumaKey }}
- name: USER_AGENT
  valueFrom:
    configMapKeyRef:
      name: {{ include "nff-ticket-monitor.name" . }}-config
      key: USER_AGENT
- name: REQUEST_TIMEOUT_SECONDS
  valueFrom:
    configMapKeyRef:
      name: {{ include "nff-ticket-monitor.name" . }}-config
      key: REQUEST_TIMEOUT_SECONDS
- name: MIN_REQUEST_INTERVAL_SECONDS
  valueFrom:
    configMapKeyRef:
      name: {{ include "nff-ticket-monitor.name" . }}-config
      key: MIN_REQUEST_INTERVAL_SECONDS
- name: MAX_RETRIES
  valueFrom:
    configMapKeyRef:
      name: {{ include "nff-ticket-monitor.name" . }}-config
      key: MAX_RETRIES
- name: BACKOFF_BASE_SECONDS
  valueFrom:
    configMapKeyRef:
      name: {{ include "nff-ticket-monitor.name" . }}-config
      key: BACKOFF_BASE_SECONDS
- name: BACKOFF_MAX_SECONDS
  valueFrom:
    configMapKeyRef:
      name: {{ include "nff-ticket-monitor.name" . }}-config
      key: BACKOFF_MAX_SECONDS
- name: ANNOUNCE_ENABLED
  valueFrom:
    configMapKeyRef:
      name: {{ include "nff-ticket-monitor.name" . }}-config
      key: ANNOUNCE_ENABLED
- name: ANNOUNCE_HOME_ONLY
  valueFrom:
    configMapKeyRef:
      name: {{ include "nff-ticket-monitor.name" . }}-config
      key: ANNOUNCE_HOME_ONLY
- name: WATCH_JSON
  valueFrom:
    configMapKeyRef:
      name: {{ include "nff-ticket-monitor.name" . }}-config
      key: WATCH_JSON
- name: NORMAL_INTERVAL_SECONDS
  valueFrom:
    configMapKeyRef:
      name: {{ include "nff-ticket-monitor.name" . }}-config
      key: NORMAL_INTERVAL_SECONDS
- name: RESALE_INTERVAL_SECONDS
  valueFrom:
    configMapKeyRef:
      name: {{ include "nff-ticket-monitor.name" . }}-config
      key: RESALE_INTERVAL_SECONDS
- name: HOT_INTERVAL_SECONDS
  valueFrom:
    configMapKeyRef:
      name: {{ include "nff-ticket-monitor.name" . }}-config
      key: HOT_INTERVAL_SECONDS
- name: HOT_WINDOW_BEFORE_SECONDS
  valueFrom:
    configMapKeyRef:
      name: {{ include "nff-ticket-monitor.name" . }}-config
      key: HOT_WINDOW_BEFORE_SECONDS
- name: HOT_WINDOW_AFTER_SECONDS
  valueFrom:
    configMapKeyRef:
      name: {{ include "nff-ticket-monitor.name" . }}-config
      key: HOT_WINDOW_AFTER_SECONDS
- name: MAX_RUN_SECONDS
  valueFrom:
    configMapKeyRef:
      name: {{ include "nff-ticket-monitor.name" . }}-config
      key: MAX_RUN_SECONDS
- name: NOTIFY_COOLDOWN_SECONDS
  valueFrom:
    configMapKeyRef:
      name: {{ include "nff-ticket-monitor.name" . }}-config
      key: NOTIFY_COOLDOWN_SECONDS
- name: PARSE_FAILURE_ALERT_COOLDOWN_SECONDS
  valueFrom:
    configMapKeyRef:
      name: {{ include "nff-ticket-monitor.name" . }}-config
      key: PARSE_FAILURE_ALERT_COOLDOWN_SECONDS
{{- end -}}
