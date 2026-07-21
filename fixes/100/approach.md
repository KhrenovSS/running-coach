# Bug #100: `suspect_flags` inverted logic

## Root Cause

In `src/analysis/__init__.py:214-218`, the `too_short` suspect flag was placed in the `else` branch of the `cleaning_log` check:

```python
if cleaning_log:
    result['cleaning_log'] = cleaning_log
else:
    if result['duration_minutes'] < 2.0 and result['total_distance_km'] > 0.3:
        result['suspect_flags'] = ['too_short']
```

This means:
- When GPS cleaning **did** find issues (cleaning_log is non-empty) → no suspect_flags set
- When GPS cleaning found **nothing** (cleaning_log is empty) → suspect_flags set for "too_short"

This is inverted. Suspicious GPS points should contribute to suspect_flags, and `too_short` should be independent of GPS cleaning.

## Fix

1. Set `suspect_flags` from `cleaning_log` entries when GPS cleaning happened (non-empty)
2. Check `too_short` unconditionally — a short track is suspicious regardless of GPS cleaning
3. Merge both sources into a single `suspect_flags` list
