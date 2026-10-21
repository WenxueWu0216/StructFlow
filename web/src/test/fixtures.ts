import type { CashFlowRow, Pool, Scenario } from "../api";

export const POOL: Pool = {
  id: 1,
  name: "FNMA-SYN-1000",
  pass_through_rate: 0.055,
  balance: 1200,
  wac: 0.06,
  wam: 3,
  wala: 0,
  loan_count: 2,
  created_at: "2026-10-21T00:00:00Z",
};

export function rows(n: number, balance = 1200): CashFlowRow[] {
  const principal = balance / n;
  return Array.from({ length: n }, (_, i) => ({
    month: i + 1,
    beginning_balance: balance - principal * i,
    gross_interest: 6,
    servicing_fee: 0.5,
    net_interest: 5.5,
    scheduled_principal: principal,
    prepayment: 0,
    total_principal: principal,
    ending_balance: balance - principal * (i + 1),
    cash_flow: principal + 5.5,
    smm: 0.01,
  }));
}

/** fetch stub that answers like the API; scenario speed drives the numbers. */
export function mockApi(opts: { pools?: Pool[]; priceStatus?: number } = {}) {
  const calls: { url: string; body?: unknown }[] = [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(init.body as string) : undefined;
    calls.push({ url, body });
    const json = (status: number, data: unknown) =>
      new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
    if (url === "/api/pools") return json(200, { pools: opts.pools ?? [POOL] });
    const scenario: Scenario = { model: body.model, speed: body.speed };
    if (url.endsWith("/cashflows")) {
      const n = Math.max(1, 6 - Math.round(scenario.speed / 100));
      return json(200, { pool_id: 1, scenario, wal: n / 24, rows: rows(n) });
    }
    if (url.endsWith("/price")) {
      if (opts.priceStatus && opts.priceStatus >= 400) {
        return json(opts.priceStatus, {
          error: { code: "validation_error", message: "bad", details: [{ loc: [], msg: "yield too high" }] },
        });
      }
      return json(200, {
        pool_id: 1,
        run_id: 1,
        scenario,
        price: 100 + scenario.speed / 1000,
        yield: body.yield,
        wal: 1 / (1 + scenario.speed),
        modified_duration: 2.5,
        convexity: 10,
      });
    }
    return json(404, { error: { code: "not_found", message: "nope", details: [] } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}
