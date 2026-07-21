# Bug #101: format_pace / format_duration int() truncation

## Root Cause

Both `format_pace` and `format_duration` use `int((value - m) * 60)` to compute seconds.
`int()` truncates toward zero, so fractional seconds are always rounded down.

Example: pace 5.7166 → `(5.7166 - 5) * 60 = 42.996` → `int(42.996) = 42` → displays `5:42`.
Correct result should be `5:43`.

Additionally, there is no guard against `s == 60` after rounding, which can occur due to
floating point arithmetic (e.g., rounding 59.6 → 60).

## Affected Files

- `src/analysis/utils.py:46-55` — `format_pace()`
- `src/analysis/utils.py:58-67` — `format_duration()`

## Fix Strategy

1. Replace `int(...)` with `round(...)` for seconds calculation.
2. Add overflow guard: if `s >= 60`, increment `m` by 1 and set `s = 0`.
3. Apply identical fix to both functions.
