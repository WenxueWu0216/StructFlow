# Domain notes: agency MBS pass-throughs

These notes explain the finance StructFlow implements, in plain English, with
the formulas the code uses. Every number in the worked examples is checked by a
test in `structflow/tests/test_reference_cases.py`.

## 1. What a pass-through is

A lender makes thousands of home loans. An agency (Fannie Mae, Freddie Mac,
Ginnie Mae) pools similar loans and issues a security backed by them. Each
month, the borrowers' payments come in and are *passed through* to the
security's investors, pro rata, after fees are taken out.

Investors receive two things each month:

- **Interest** at the pool's **pass-through rate** (the coupon) on the balance
  outstanding at the start of the month.
- **All principal** the borrowers paid: their scheduled amortization plus any
  prepayments.

The agency guarantees timely payment, so investors do not take credit losses.
What they do take is **prepayment risk**: borrowers can pay off early at any
time (refinancing, moving, curtailments), and nobody knows when they will.

A pool is described by a few summary numbers:

| Term | Meaning |
|---|---|
| Balance | Current unpaid principal of all loans |
| WAC | Weighted average coupon: the balance-weighted average of the loans' **note rates** (what borrowers pay) |
| WAM | Weighted average maturity: balance-weighted months remaining |
| WALA | Weighted average loan age: balance-weighted months since origination |
| Pass-through rate | The coupon paid to investors, below the WAC |

StructFlow can project either a single representative loan built from those
summaries (`Pool`) or the actual loans one by one (`LoanTape`). Loan level is
more accurate because loans with different rates, terms and ages amortize and
prepay differently; the pool's cash flow is the sum of the loans' cash flows.

## 2. Scheduled amortization

A fixed-rate mortgage has a **level monthly payment** that covers that month's
interest and pays down some principal. With balance `B`, monthly note rate
`r = note rate / 12` and `n` months remaining:

```
payment = B * r / (1 - (1 + r) ** -n)
interest = B * r
scheduled principal = payment - interest
```

Early on most of the payment is interest; principal grows each month.

**Worked example** (1,000,000 pool, 6.5% WAC, 360 months):

```
r = 0.065 / 12 = 0.00541667
payment = 1,000,000 * 0.00541667 / (1 - 1.00541667 ** -360) = 6,320.68
interest = 1,000,000 * 0.00541667 = 5,416.67
scheduled principal = 6,320.68 - 5,416.67 = 904.01
```

After a prepayment the payment is recalculated over the same remaining term,
so the balance keeps following the same amortization *shape*, just scaled
down. StructFlow's vectorized engine relies on exactly that fact (see
`structflow/src/structflow/cashflows.py`).

## 3. Servicing and guarantee fees

Borrowers pay the note rate; investors get the lower pass-through rate. The
difference, typically 25 to 75 basis points a year, is split between:

- the **servicer**, who collects payments, handles escrow and works with
  delinquent borrowers, and
- the **guarantor** (the agency), whose **guarantee fee** ("g-fee") pays for
  the credit guarantee.

Each month the strip is `balance * (note rate - pass-through rate) / 12`. It
is interest only: principal passes through in full. In the example above, with
a 6.0% pass-through rate:

```
servicing + g-fee = 1,000,000 * (0.065 - 0.060) / 12 = 416.67
net interest to investor = 1,000,000 * 0.060 / 12 = 5,000.00
```

## 4. Prepayments: CPR and SMM

Prepayment speed is quoted two ways:

- **CPR**, conditional prepayment rate: the annualized fraction of the
  remaining balance that prepays. 6% CPR means about 6% of the balance would
  prepay over a year.
- **SMM**, single monthly mortality: the fraction that prepays in one month.

They are linked by compounding, not by dividing by 12:

```
SMM = 1 - (1 - CPR) ** (1/12)
CPR = 1 - (1 - SMM) ** 12
```

6% CPR is an SMM of 0.514%, not 0.5%.

The SMM applies to the balance *after* the scheduled principal for the month:

```
prepayment = SMM * (beginning balance - scheduled principal)
ending balance = beginning balance - scheduled principal - prepayment
```

## 5. The PSA benchmark

New loans rarely prepay (people have just moved in or refinanced); seasoned
loans prepay more. The **PSA** (Public Securities Association) benchmark
captures that ramp:

- **100% PSA**: CPR is 0.2% in the loan's first month and rises by 0.2% per
  month until month 30, where it reaches 6%. It stays at 6% after that.
- Other speeds scale the whole curve: 200% PSA is 0.4% in month 1 rising to
  12%; 50% PSA tops out at 3%.

```
CPR(age) = 6% * min(age, 30) / 30 * speed / 100
```

`age` is the loan's age in the month of the payment, so a pool that is
already 18 months seasoned (WALA 18) starts at month 19 of the ramp. That is
why loan age matters and why StructFlow tracks it per loan.

PSA is a *quoting convention*, not a forecast. Desks express their prepayment
view as "this pool will pay at 180 PSA", then run the cash flows at that
speed. StructFlow caps CPR at 100% for absurdly high speeds.

**Worked example** (continuing the 1,000,000 pool, brand new, 100% PSA):

```
month-1 CPR = 0.2%,  SMM = 1 - 0.998 ** (1/12) = 0.000166820
prepayment = (1,000,000 - 904.01) * 0.000166820 = 166.67
ending balance = 1,000,000 - 904.01 - 166.67 = 998,929.32
investor cash flow = 5,000.00 + 904.01 + 166.67 = 6,070.68
```

## 6. Price and yield

Price is the present value of the investor cash flows, quoted per 100 of
current face. Yield is the single discount rate that makes the present value
equal the price. They move in opposite directions: a higher required yield
means future cash is worth less today, so the price falls.

StructFlow's conventions:

- yields compound **monthly** (a "mortgage yield"); month `t` is discounted by
  `(1 + y/12) ** t`;
- settlement is on a payment date with **no payment delay** and no accrued
  interest (real agency pools pay 14 to 55 days after the accrual month ends;
  that delay would lower the price slightly);
- price per 100 = `100 * sum(CF_t / (1 + y/12) ** t) / current balance`.

Two useful facts the tests check:

- **Priced at its coupon, a pass-through is worth par (100) at any
  prepayment speed.** Each month the investor earns exactly the discount
  rate on the outstanding balance, so the present value telescopes back to
  the balance.
- **Premium and discount behave oppositely with speed.** A bond bought above
  par (premium) loses value when prepayments speed up, because the investor
  gets 100 back sooner on something they paid more than 100 for. A discount
  bond gains for the same reason.

Going from price to yield has no closed form, so `yield_from_price` solves
for it numerically. Price is strictly decreasing in yield when cash flows are
non-negative, so there is exactly one answer; the solver uses Newton steps
inside a bisection bracket, which keeps Newton's speed and bisection's
guarantee of converging.

## 7. Weighted average life (WAL)

WAL is the average time until each dollar of **principal** is repaid,
weighted by the amount of principal:

```
WAL (years) = sum(t/12 * principal_t) / sum(principal_t)
```

Interest is ignored. WAL is the standard way to compare how long MBS cash
flows last: a 30-year pool at 100% PSA might have a WAL near 11 years, and at
300% PSA near 6. Faster prepayments always shorten WAL.

**Worked example**: a 0% loan of 1,200 over 12 months pays 100 of principal
each month, so `WAL = (100/12) * (1 + 2 + ... + 12) / 1,200 = 0.54 years`.

## 8. Duration and convexity

**Modified duration** measures price sensitivity to yield: the approximate
percentage price change for a 1.00 (100 percentage point) change in yield, so
duration 6 means roughly a 0.06% price drop per basis point.

```
Macaulay duration = sum(t/12 * PV_t) / price        (years)
modified duration = Macaulay / (1 + y/12)
                  = -(1/P) dP/dy
```

**Convexity** is the second-order term: how much duration itself changes as
yield moves.

```
convexity = (1/P) d2P/dy2 = sum(t (t + 1) / 144 * PV_t) / (P * (1 + y/12) ** 2)
```

Together: `dP/P ≈ -duration * dy + 0.5 * convexity * dy**2`.

StructFlow reports **static** (or "modified") measures: the cash flows are
held fixed while the yield moves. Real MBS have *negative convexity* because
prepayments react to rates (rates fall, borrowers refinance, the pool shortens
just when you would want it to lengthen). Capturing that needs **effective
duration**: re-project cash flows with a rate-sensitive prepayment model at
shifted rates. That needs a prepayment model linked to rates, which is out of
scope here; comparing static measures across PSA scenarios gives a feel for
the effect.

## 9. Where each idea lives in the code

| Concept | Code |
|---|---|
| CPR/SMM conversion, PSA ramp | `structflow/src/structflow/prepay.py` |
| Amortization, fees, prepayments, projection | `structflow/src/structflow/cashflows.py` |
| Price/yield, WAL, duration, convexity | `structflow/src/structflow/pricing.py` |
| Curve interpolation for the nightly batch | `structflow/src/structflow/curve.py` |
