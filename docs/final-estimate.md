# Final GDP estimate

The home page adds the status strip and extends the last published estimate and
its empirical error bands to ABS release day only for a certified combination.
The dashed extension is a visual carry, not a forecast update or a GDP actual.

The extra run starts in the afternoon (Sydney time) on the day before GDP. It
leaves Monday's cadence and the legacy release-morning job alone. The date gate
checks the GDP date and prior actual already captured in the pipeline's
`data/latest.json`. After v2 refreshes its inputs and publishes a final-day
vintage, the workflow dispatches v3 to combine against that exact vintage. A
refusal, a late job, a missing observation or a carry cannot generate the label.
The usual estimate stays in place if the special run cannot finish. The regular
Monday run can also certify completion; the special run can pick up revisions.

"Complete" applies to the **model inputs**, not every series shown in the
indicator table or ABS GDP itself. v2 checks its selected transformed inputs;
the legacy NAB Stocks candidate has no expected new observation while the
publisher omits it. v3 checks its transformed monthly panel; a single documented
turn-of-year Ai Group omission is allowed only if the adjacent observation is
present. The quarterly GDP, GDI and labour-cost rows published in National
Accounts are not advance inputs for that same quarter. None of these checks
change the models, their selection rules or the historical vintage cutoffs.

For each quarter, the monthly count is the intersection of the months complete
in the two models in that same run. A missing or carried certificate shows a
dash, rather than falling back to the old count of any available observation.
The status strip turns on with the first complete current-quarter publication.
Subsequent runs can use revised data or new readings from later months; the
models' input windows stay unchanged. Old points remain in the archive.

The certificate binds the target, exact publication and official release
instant (11:30 Sydney time). The label expires at release even on an open tab,
and cannot migrate to the new current quarter.

The first scheduled use after deployment is not considered verified until the
v2 and v3 jobs and the Pages deployment finish. Check their Actions logs for a
named missing input or refusal if the badge does not appear.
