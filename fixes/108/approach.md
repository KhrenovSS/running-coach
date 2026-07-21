# Bug #108: Oscillation `avg_pace = 0.0` with empty slice

## Root Cause

In `detect_pace_oscillations()` at `src/analysis/oscillation.py:113`, the average pace
of a phase is computed as:

```python
avg_pace = sum(smoothed_paces[phase_start:i]) / max(1, i - phase_start)
```

When `phase_start == i` (which happens at phase boundaries where a single point creates
a zero-length slice), the slice is empty: `sum([]) = 0` and `max(1, 0) = 1`, producing
`avg_pace = 0.0`.

This is **silent data corruption**: pace is always > 3 min/km for humans, so `0.0` is
nonsensical and breaks downstream analytics (averages, UI display, coach recommendations).

## Trigger Conditions

- `phase_start == i` when a type transition happens at consecutive indices (e.g., all
  values equal to threshold produce `<= threshold` vs `> threshold` alternation at
  exact boundary points).
- Most likely with monotonous runs where `_adaptive_pace_gap` collapses the gap,
  pushing threshold close to data values.

## Fix

1. Guard `i > phase_start` before computing avg_pace in the main loop (line 113).
2. Fall back to `base_pace` (defined at line 96) when the slice is empty.
3. Apply the same guard to the last-phase computation (line 129), though `len(smoothed_paces) - phase_start` is always >= 1 for a valid last phase, making the fix primarily defensive.

## Files Changed

- `src/analysis/oscillation.py` — guard avg_pace computation
- `tests/test_oscillation.py` — regression tests for zero-length phases
