import { useEffect, useState } from "react";
import { api, type CashFlowResponse, type Pool, type PriceResponse, type Scenario } from "./api";
import { BalanceChart } from "./components/BalanceChart";
import { CashFlowTable } from "./components/CashFlowTable";
import { ScenarioEditor } from "./components/ScenarioEditor";
import { fmtMoney, fmtNum, fmtPct, fmtScenario } from "./format";

export const COLORS = ["#2f6fde", "#d9822b", "#1a9e77"];

const DEFAULT_SCENARIOS: Scenario[] = [
  { model: "PSA", speed: 100 },
  { model: "PSA", speed: 250 },
  { model: "CPR", speed: 15 },
];

interface Result {
  scenario: Scenario;
  cashflows: CashFlowResponse;
  pricing: PriceResponse;
}

export default function App() {
  const [pools, setPools] = useState<Pool[]>([]);
  const [poolId, setPoolId] = useState<number | null>(null);
  const [yieldPct, setYieldPct] = useState<number>(NaN);
  const [scenarios, setScenarios] = useState<Scenario[]>(DEFAULT_SCENARIOS);
  const [results, setResults] = useState<Result[] | null>(null);
  const [selected, setSelected] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listPools()
      .then((ps) => {
        setPools(ps);
        if (ps.length > 0) {
          setPoolId(ps[0].id);
          setYieldPct(+(ps[0].pass_through_rate * 100).toFixed(3));
        }
      })
      .catch((e: Error) => setError(`Could not load pools: ${e.message}`));
  }, []);

  const pool = pools.find((p) => p.id === poolId) ?? null;

  function choosePool(id: number) {
    setPoolId(id);
    setResults(null);
    const p = pools.find((x) => x.id === id);
    if (p) setYieldPct(+(p.pass_through_rate * 100).toFixed(3));
  }

  async function run() {
    if (pool === null) return;
    setLoading(true);
    setError(null);
    try {
      const out = await Promise.all(
        scenarios.map(async (scenario) => {
          const [cashflows, pricing] = await Promise.all([
            api.cashflows(pool.id, scenario),
            api.price(pool.id, scenario, yieldPct / 100),
          ]);
          return { scenario, cashflows, pricing };
        }),
      );
      setResults(out);
      setSelected(0);
    } catch (e) {
      setResults(null);
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  const invalid =
    pool === null || Number.isNaN(yieldPct) || scenarios.some((s) => Number.isNaN(s.speed));

  return (
    <main>
      <header>
        <h1>StructFlow</h1>
        <p>Agency pass-through cash flows and pricing under prepayment scenarios</p>
      </header>

      <section className="panel controls">
        <div className="pool-pick">
          <label htmlFor="pool">Pool</label>
          <select
            id="pool"
            value={poolId ?? ""}
            onChange={(e) => choosePool(Number(e.target.value))}
            disabled={pools.length === 0}
          >
            {pools.length === 0 && <option value="">No pools loaded</option>}
            {pools.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          {pool && (
            <dl className="pool-facts">
              <dt>Balance</dt>
              <dd>{fmtMoney(pool.balance)}</dd>
              <dt>Loans</dt>
              <dd>{pool.loan_count}</dd>
              <dt>WAC</dt>
              <dd>{fmtPct(pool.wac)}</dd>
              <dt>Pass-through</dt>
              <dd>{fmtPct(pool.pass_through_rate)}</dd>
              <dt>WAM / WALA</dt>
              <dd>
                {pool.wam} / {pool.wala}
              </dd>
            </dl>
          )}
          <label htmlFor="yield">Yield (%, monthly compounding)</label>
          <input
            id="yield"
            type="number"
            step={0.125}
            value={Number.isNaN(yieldPct) ? "" : yieldPct}
            onChange={(e) => setYieldPct(e.target.valueAsNumber)}
          />
        </div>
        <div className="scenarios">
          {scenarios.map((s, i) => (
            <ScenarioEditor
              key={i}
              index={i}
              color={COLORS[i]}
              scenario={s}
              onChange={(next) => setScenarios(scenarios.map((x, j) => (j === i ? next : x)))}
            />
          ))}
        </div>
        <button type="button" onClick={run} disabled={invalid || loading}>
          {loading ? "Running…" : "Run scenarios"}
        </button>
      </section>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      {results && (
        <>
          <section className="panel">
            <h2>Scenario comparison</h2>
            <table className="compare">
              <thead>
                <tr>
                  <th />
                  {results.map((r, i) => (
                    <th key={i} style={{ color: COLORS[i] }}>
                      {fmtScenario(r.scenario)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <Metric label="Price (per 100)" results={results} get={(r) => fmtNum(r.pricing.price, 4)} />
                <Metric label="Yield" results={results} get={(r) => fmtPct(r.pricing.yield)} />
                <Metric label="WAL (years)" results={results} get={(r) => fmtNum(r.pricing.wal)} />
                <Metric
                  label="Modified duration"
                  results={results}
                  get={(r) => fmtNum(r.pricing.modified_duration)}
                />
                <Metric label="Convexity" results={results} get={(r) => fmtNum(r.pricing.convexity, 1)} />
                <Metric
                  label="Total net interest"
                  results={results}
                  get={(r) => fmtMoney(totalInterest(r.cashflows))}
                />
              </tbody>
            </table>
          </section>

          <section className="panel">
            <h2>Outstanding balance</h2>
            <BalanceChart
              series={results.map((r, i) => ({
                label: fmtScenario(r.scenario),
                color: COLORS[i],
                values: r.cashflows.rows.map((row) => row.ending_balance),
              }))}
            />
          </section>

          <section className="panel">
            <h2>Monthly cash flows</h2>
            <div role="tablist" className="tabs">
              {results.map((r, i) => (
                <button
                  key={i}
                  role="tab"
                  aria-selected={selected === i}
                  onClick={() => setSelected(i)}
                  style={{ borderBottomColor: selected === i ? COLORS[i] : "transparent" }}
                >
                  {fmtScenario(r.scenario)}
                </button>
              ))}
            </div>
            <CashFlowTable rows={results[selected].cashflows.rows} />
          </section>
        </>
      )}
    </main>
  );
}

function totalInterest(cf: CashFlowResponse): number {
  return cf.rows.reduce((sum, r) => sum + r.net_interest, 0);
}

function Metric({
  label,
  results,
  get,
}: {
  label: string;
  results: Result[];
  get: (r: Result) => string;
}) {
  return (
    <tr>
      <th scope="row">{label}</th>
      {results.map((r, i) => (
        <td key={i}>{get(r)}</td>
      ))}
    </tr>
  );
}
