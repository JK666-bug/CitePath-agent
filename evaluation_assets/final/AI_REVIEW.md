# Machine-assisted draft review

An additional AI reviewer checked the candidate MCQ keys, rubric/page links,
evidence scope and workflow boundaries against the downloaded lecture text.
This was a draft-quality review, not either of the two required human annotations.
Both human annotation sheets remain blank.

The review led to these changes before the preparation snapshot:

- MC-06 now asks about reselecting the hash function, rather than sounding like a
  question about the new table size.
- MC-20 asks for a tight bound and uses Theta alternatives to avoid multiple valid
  but loose Big-O upper bounds.
- EV-06-2 explains why the traversal successor has an available left-child link.
- EV-04-3 explicitly asks for traversal cost; EV-01-3 explicitly includes the
  pigeonhole argument when the table is smaller than the key universe.
- SA-03, SA-04 and SA-07 now explicitly ask for every concept in their rubrics.
- All 20 final MCQ responses select one valid option. Invalid/blank/multiple-option
  input handling remains in the development/API regression tests.
- Workflow scenarios now specify duplicate submission, independent Q&A, process
  restart, draft restoration and timeout/retry actions where applicable, along
  with checks that saved grades/questions remain unchanged.

The 40 short-answer inputs are four authored responses for each of ten questions.
Their intended point coverage is only a candidate hint; it is not a human label.
The 30 supported and 10 unsupported evidence classifications also need independent
human confirmation. System predictions and real workflow observations are absent.
