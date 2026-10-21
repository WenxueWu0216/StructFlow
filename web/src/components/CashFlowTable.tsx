import type { CashFlowRow } from "../api";
import { fmtMoney, fmtPct, smmToCpr } from "../format";

export function CashFlowTable({ rows }: { rows: CashFlowRow[] }) {
  return (
    <div className="table-scroll">
      <table className="cashflows">
        <thead>
          <tr>
            <th>Month</th>
            <th>Beginning balance</th>
            <th>Net interest</th>
            <th>Servicing + g-fee</th>
            <th>Scheduled principal</th>
            <th>Prepayment</th>
            <th>Ending balance</th>
            <th>CPR</th>
            <th>Investor cash flow</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.month}>
              <td>{r.month}</td>
              <td>{fmtMoney(r.beginning_balance)}</td>
              <td>{fmtMoney(r.net_interest)}</td>
              <td>{fmtMoney(r.servicing_fee)}</td>
              <td>{fmtMoney(r.scheduled_principal)}</td>
              <td>{fmtMoney(r.prepayment)}</td>
              <td>{fmtMoney(r.ending_balance)}</td>
              <td>{fmtPct(smmToCpr(r.smm), 2)}</td>
              <td>{fmtMoney(r.cash_flow)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
