import { fmtMoney, fmtPct, fmtScenario, smmToCpr } from "./format";

test("formats numbers for the tables", () => {
  expect(fmtMoney(1234567.89)).toBe("1,234,568");
  expect(fmtPct(0.055)).toBe("5.500%");
  expect(fmtScenario({ model: "PSA", speed: 150 })).toBe("150 PSA");
});

test("smmToCpr inverts the SMM conversion", () => {
  // 6% CPR <-> SMM 0.00514301 (see structflow tests)
  expect(smmToCpr(1 - 0.94 ** (1 / 12))).toBeCloseTo(0.06, 12);
});
