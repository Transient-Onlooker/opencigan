# NEIS meal nutrition fields

`backend.neis.Meal` carries the meal fields returned by NEIS. Its constructor keeps the original positional order (`date`, `meal_type`, `menu`, `calories`, `origin`) and appends the optional `nutrition` field, so existing positional callers remain compatible.

| Meal field | NEIS source | Meaning |
| --- | --- | --- |
| `calories` | `CAL_INFO` | Energy information, preserved as the source string |
| `origin` | `ORPLC_INFO` | Ingredient origin information, preserved as the source string |
| `nutrition` | `NTR_INFO` | Nutrient information, preserved as the source string |

These fields are optional. A missing, blank, or non-string NEIS value becomes `None`; the client does not calculate or infer values. Each optional field is capped at 4,000 characters. The underlying NEIS response is limited to 16 MiB, and pagination rejects reported totals above 100,000 rows. The row limit bounds memory and requests if an upstream response reports an implausibly large total or fails to make progress.

The meals API exposes these as optional `calories`, `origin`, and `nutrition` string-or-null fields. The frontend type accepts them; user interface presentation remains pending.
