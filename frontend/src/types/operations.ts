export type StatusTone = "neutral" | "info" | "warning" | "success" | "danger";

export type Kpi = {
  label: string;
  value: string;
  delta: string;
  tone: StatusTone;
};

export type OperationRow = {
  id: string;
  ref: string;
  status: string;
  statusTone: StatusTone;
  warehouse: string;
  owner: string;
  priority: string;
  quantity: string;
  sla: string;
  raw?: Record<string, unknown>;
  timeline?: TimelineEvent[];
};

export type TimelineEvent = {
  id: string;
  label: string;
  actor: string;
  at: string;
  details: string;
};

export type OperationModule = {
  key: string;
  label: string;
  path: string;
  description: string;
  apiPath: string;
  primaryAction: string;
  columns: string[];
  permissions: string[];
};
