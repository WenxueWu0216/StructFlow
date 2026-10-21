// Typed client for the StructFlow REST API (see /openapi.json on the API).

export type PrepayModel = "PSA" | "CPR";

export interface Scenario {
  model: PrepayModel;
  speed: number;
}

export interface Pool {
  id: number;
  name: string;
  pass_through_rate: number;
  balance: number;
  wac: number;
  wam: number;
  wala: number;
  loan_count: number;
  created_at: string;
}

export interface CashFlowRow {
  month: number;
  beginning_balance: number;
  gross_interest: number;
  servicing_fee: number;
  net_interest: number;
  scheduled_principal: number;
  prepayment: number;
  total_principal: number;
  ending_balance: number;
  cash_flow: number;
  smm: number;
}

export interface CashFlowResponse {
  pool_id: number;
  scenario: Scenario;
  wal: number;
  rows: CashFlowRow[];
}

export interface PriceResponse {
  pool_id: number;
  run_id: number;
  scenario: Scenario;
  price: number;
  yield: number;
  wal: number;
  modified_duration: number;
  convexity: number;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  const body = await resp.json().catch(() => null);
  if (!resp.ok) {
    const err = body?.error;
    const detail = err?.details?.map((d: { msg: string }) => d.msg).join("; ");
    throw new ApiError(resp.status, detail || err?.message || `HTTP ${resp.status}`);
  }
  return body as T;
}

export const api = {
  listPools: () => request<{ pools: Pool[] }>("/pools").then((r) => r.pools),
  cashflows: (poolId: number, scenario: Scenario) =>
    request<CashFlowResponse>(`/pools/${poolId}/cashflows`, {
      method: "POST",
      body: JSON.stringify(scenario),
    }),
  price: (poolId: number, scenario: Scenario, yieldRate: number) =>
    request<PriceResponse>(`/pools/${poolId}/price`, {
      method: "POST",
      body: JSON.stringify({ ...scenario, yield: yieldRate }),
    }),
};
