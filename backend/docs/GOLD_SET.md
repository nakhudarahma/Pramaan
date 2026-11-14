# Evaluation gold set

Status: specification for the 40-question evaluation. Results and baseline
comparisons must be recorded from a run against the evaluation fixture; no
quality figures are claimed here.

## Groups

| Group | Count | What it tests |
| --- | --- | --- |
| A. Direct volatile | 10 | Exact fee/date value and citation |
| B. Static policy | 6 | Retrieval-grounded policy answer and chunk citation |
| C. Scope-sensitive | 8 | Wrong-scope rate across course, semester and academic year |
| D. Superseded information | 6 | Stale-answer rate and supersession notice |
| E. Contradictory notices | 4 | Dispute state and refusal to pick a value |
| F. Unanswerable | 6 | Correct abstention and unanswered logging |

## Questions

| # | Group | Question | Expected behaviour |
| --- | --- | --- | --- |
| 1 | A | What is the late fee? | Current active fee, source citation |
| 2 | A | How much is the late fee for late payment? | Same active fee, no stale value |
| 3 | A | What fine applies after the fee deadline? | Active fee or unavailable; never invented |
| 4 | A | When is the mid-semester exam? | Active exam date with citation and calendar offer |
| 5 | A | What is the exam start date? | Active exam date with citation |
| 6 | A | What is the last date to pay the fee? | Active fee deadline with citation |
| 7 | A | When is the exam form deadline? | Active deadline with citation |
| 8 | A | What is the result date? | Active result date or unavailable |
| 9 | A | When does the semester start? | Active semester date with citation |
| 10 | A | What is the holiday date? | Active holiday date or unavailable |
| 11 | B | What is the attendance requirement? | Narrative answer from published chunk |
| 12 | B | How much attendance is needed to sit for exams? | 75% only if in the cited chunk |
| 13 | B | What happens if attendance is below the requirement? | Policy excerpt, no invented penalty |
| 14 | B | Can attendance shortage be condoned? | Only if the notice says so; otherwise unavailable |
| 15 | B | What is the hostel allocation policy? | Published policy with chunk citation |
| 16 | B | What documents are needed for a scholarship? | Published policy with chunk citation |
| 17 | C | What is the late fee for B.Tech Semester 4? | Scoped active fact or scope clarification |
| 18 | C | What is the late fee for B.Com Semester 2? | Must not return the B.Tech value |
| 19 | C | What is the hostel fee for the 2026-27 year? | Matching academic-year fact only |
| 20 | C | What is the hostel fee for the 2025-26 year? | Matching academic-year fact only |
| 21 | C | What is the exam date for Semester 6? | Matching semester fact or clarification |
| 22 | C | What is the exam date for a different course? | Must not return another course's date |
| 23 | C | Mera Sem 5 ka fee kitna hai? | Hinglish slot parsing; correct or clarification |
| 24 | C | What is the fee for a student with no semester selected? | Broad fact may apply; narrower fact must clarify |
| 25 | D | What is the late fee? | Current value, supersession line shows old value |
| 26 | D | Has the late fee changed? | Current value plus change context |
| 27 | D | When is the exam? | Current date, not the superseded date |
| 28 | D | What was the previous exam date? | Change history if exposed, never current-answer confusion |
| 29 | D | Which notice is currently authoritative? | New notice cited; old notice marked superseded |
| 30 | D | Is the old fee still valid? | No; current value or outdated state |
| 31 | E | When is the lab exam? | `disputed` state, both sources cited |
| 32 | E | What is the lab exam date according to the notices? | No guessed value; dispute card |
| 33 | E | Which lab exam notice should I trust? | Explicit disagreement; contact office |
| 34 | E | Is the lab exam on the date in the first notice? | Must not silently choose one notice |
| 35 | F | When is the re-exam? | `unavailable`; question logged |
| 36 | F | What is the cultural fest date? | `unavailable` if not published; logged |
| 37 | F | What is the scholarship last date? | `unavailable` if no approved fact; logged |
| 38 | F | What is the placement fee? | `unavailable`; no fabricated amount |
| 39 | F | Who is the new principal? | `unavailable` unless in a published notice |
| 40 | F | What is the bus route timing? | `unavailable`; no invented schedule |

## Metrics to record

- Exact structured-value match rate, with citation present.
- Wrong-scope answer rate.
- Stale-answer rate for group D.
- Dispute-handling rate for group E.
- Correct-abstention rate for group F.
- Median latency and unanswered-log coverage.

Run the same set against a retrieval-only baseline and a prompt-only baseline;
report measured results without promising target numbers in advance.
