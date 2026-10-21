# structflow

Pure-Python (NumPy/pandas) library for projecting agency MBS pass-through cash
flows and computing price, yield, WAL, modified duration and convexity. It has
no web or database dependencies; the StructFlow API and the nightly batch job
both import it.

```python
from structflow import Pool, PSA, project_cashflows, analytics_from_yield

pool = Pool(balance=1_000_000, wac=0.065, wam=360, pass_through_rate=0.06)
cf = project_cashflows(pool, PSA(150))
print(analytics_from_yield(cf, 0.06))
```

See `../docs/domain.md` for the finance behind each function.
