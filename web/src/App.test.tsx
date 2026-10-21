import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";
import { mockApi, POOL } from "./test/fixtures";

afterEach(() => vi.unstubAllGlobals());

test("loads pools and defaults the yield to the pass-through rate", async () => {
  mockApi();
  render(<App />);
  expect(await screen.findByRole("option", { name: POOL.name })).toBeInTheDocument();
  expect(screen.getByLabelText(/Yield/)).toHaveValue(5.5);
  expect(screen.getByText("6.000%")).toBeInTheDocument(); // WAC
});

test("runs three scenarios and compares them side by side", async () => {
  const calls = mockApi();
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole("option", { name: POOL.name });

  const speed2 = screen.getByLabelText("Speed (% PSA)", { selector: "#scenario-1-speed" });
  await user.clear(speed2);
  await user.type(speed2, "300");
  await user.click(screen.getByRole("button", { name: "Run scenarios" }));

  const compare = (await screen.findByText("Scenario comparison")).closest("section")!;
  const headers = within(compare).getAllByRole("columnheader").map((h) => h.textContent);
  expect(headers).toEqual(["", "100 PSA", "300 PSA", "15 CPR"]);
  const priceRow = within(compare).getByRole("row", { name: /Price/ });
  expect(within(priceRow).getAllByRole("cell").map((c) => c.textContent)).toEqual([
    "100.1000",
    "100.3000",
    "100.0150",
  ]);

  // Stub rows pay 5.5 of net interest a month for 6 - speed/100 months: 5, 3 and 6 months.
  const interestRow = within(compare).getByRole("row", { name: /Total net interest/ });
  expect(within(interestRow).getAllByRole("cell").map((c) => c.textContent)).toEqual([
    "28",
    "17",
    "33",
  ]);

  const priceCalls = calls.filter((c) => c.url.endsWith("/price"));
  expect(priceCalls.map((c) => c.body)).toEqual([
    { model: "PSA", speed: 100, yield: 0.055 },
    { model: "PSA", speed: 300, yield: 0.055 },
    { model: "CPR", speed: 15, yield: 0.055 },
  ]);

  // One line per scenario on the chart.
  expect(document.querySelectorAll(".chart path")).toHaveLength(3);
});

test("switches the cash flow table between scenarios", async () => {
  mockApi();
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole("option", { name: POOL.name });
  await user.click(screen.getByRole("button", { name: "Run scenarios" }));

  const cashflowRows = () => document.querySelectorAll(".cashflows tbody tr").length;
  await screen.findByRole("tab", { name: "100 PSA" });
  expect(cashflowRows()).toBe(5); // stub: 6 - 1 months at 100 PSA
  await user.click(screen.getByRole("tab", { name: "15 CPR" }));
  expect(screen.getByRole("tab", { name: "15 CPR" })).toHaveAttribute("aria-selected", "true");
  expect(cashflowRows()).toBe(6);
});

test("shows API validation errors", async () => {
  mockApi({ priceStatus: 422 });
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole("option", { name: POOL.name });
  await user.click(screen.getByRole("button", { name: "Run scenarios" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("yield too high");
  expect(screen.queryByText("Scenario comparison")).not.toBeInTheDocument();
});

test("disables running when there are no pools or inputs are blank", async () => {
  mockApi({ pools: [] });
  render(<App />);
  expect(await screen.findByRole("option", { name: "No pools loaded" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Run scenarios" })).toBeDisabled();
});
