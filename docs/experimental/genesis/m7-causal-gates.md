# M7-E2 — Guarded causal capability gates

The M7 executor compares five typed arms from one `RootSnapshot`: control,
treatment, placebo, ablation, and transplant. Scores are derived from the
post-promotion HIDDEN/OOD/compositional measurement; necessity, sufficiency,
and placebo separation are re-derived from those arm scores.

It does **not** manufacture CFI. A sealed external `CFIReport` is an input and
its hash is revalidated. If it is `INCOMPLETE` or `FAIL`, the certificate is
`NOT_PROVEN` even when all observed causal contrasts are favorable.

This is an intermediate guard for M7-E. The M7-F durable replay work must bind
the report and arms into the M5/M6 historical trace before GE-I can be claimed.
