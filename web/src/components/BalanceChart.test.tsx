import { render } from "@testing-library/react";
import { BalanceChart, linePath } from "./BalanceChart";

test("linePath scales months and balances into the plot area", () => {
  // 2 months on a 100 x 50 plot with yMax 10: month 1 -> x 50, month 2 -> x 100;
  // value 10 -> y 0 (top), value 0 -> y 50 (bottom).
  expect(linePath([10, 0], 2, 10, 100, 50)).toBe("M50.0,0.0L100.0,50.0");
  expect(linePath([], 2, 10, 100, 50)).toBe("");
});

test("draws one path and one legend entry per series", () => {
  const { container } = render(
    <BalanceChart
      series={[
        { label: "100 PSA", color: "red", values: [3, 2, 1, 0] },
        { label: "300 PSA", color: "blue", values: [2, 0] },
      ]}
    />,
  );
  expect(container.querySelectorAll("path")).toHaveLength(2);
  expect(container.querySelector(".legend")).toHaveTextContent("100 PSA300 PSA");
});
