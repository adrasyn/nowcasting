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
The usual estimate stays in place if the special run cannot finish.

"Complete" applies to the **model inputs**, not every series shown in the
indicator table or ABS GDP itself. v2 checks its selected transformed inputs;
the legacy NAB Stocks candidate has no expected new observation while the
publisher omits it. v3 checks its transformed monthly panel; a single documented
turn-of-year Ai Group omission is allowed only if the adjacent observation is
present. The quarterly GDP, GDI and labour-cost rows published in National
Accounts are not advance inputs for that same quarter. None of these checks
change the models, their selection rules or the historical vintage cutoffs.

The certification records the target quarter, run date, exact publication and
the Sydney release instant (11:30 local time). During that window the current
combination is locked against normal reruns. In an open browser tab the label
expires at that instant; when the observed GDP quarter advances, the previous
certification cannot migrate to the new card. The final vintage stays in the
archive.

The first scheduled use after deployment is not considered verified until the
v2 and v3 jobs and the Pages deployment finish. Check their Actions logs for a
named missing input or refusal if the badge does not appear.
