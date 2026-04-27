import { apiGet, apiPost } from "./client";

export type TransferLine = {
  id: string;
  line_number: number;
  item_ref: string;
  requested_qty: string;
  shipped_qty: string;
  received_qty: string;
  difference_qty: string;
  uom: string;
  warehouse_ref: string;
};

export type TransferOrder = {
  id: string;
  transfer_number: string;
  status: string;
  origin_warehouse_ref: string;
  destination_warehouse_ref: string;
  requested_by: string;
  approved_by: string;
  reason: string;
  lines_count?: number;
  lines?: TransferLine[];
};

type CommandResult<T> = {
  result: T;
};

export async function fetchTransfers() {
  const response = await apiGet<TransferOrder>("/api/v1/transfers/");
  if (response.error) throw new Error(response.error.message);
  return response.results ?? [];
}

export async function createTransfer(payload: {
  origin_warehouse_ref: string;
  destination_warehouse_ref: string;
  reason?: string;
  lines: Array<{ item_ref: string; requested_qty: string; uom: string }>;
}) {
  const response = await apiPost<CommandResult<TransferOrder>>("/api/v1/transfers/", payload);
  return response.result;
}

export async function transferCommand(
  transferId: string,
  command: "approve" | "prepare" | "dispatch" | "receive" | "close",
  payload: Record<string, unknown> = {},
) {
  const response = await apiPost<CommandResult<TransferOrder>>(`/api/v1/transfers/${transferId}/${command}`, payload);
  return response.result;
}
