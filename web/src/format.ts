const money = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

export const fmtMoney = (x: number): string => money.format(x);
export const fmtPct = (x: number, digits = 3): string => `${(x * 100).toFixed(digits)}%`;
export const fmtNum = (x: number, digits = 2): string => x.toFixed(digits);
export const fmtScenario = (s: { model: string; speed: number }): string =>
  `${s.speed} ${s.model}`;

/** Annual CPR implied by a monthly SMM: 1 - (1 - SMM)^12. */
export const smmToCpr = (smm: number): number => 1 - (1 - smm) ** 12;
