# Evaluation report: Constructive News AI

Run `run-20261009-1043.jsonl` · data as of 2026-10-09 · 30 questions · 36 distinct stories retrieved

## Summary

| Criterion (from the capstone brief) | Score | How it is measured |
|---|---|---|
| **Accuracy** | **100%** | Judge model grades each answer against the exact sources it was given (supported 1, partly 0.5, unsupported 0); 21 answers. Required facts present: 10/11. |
| **Citation correctness** | **100%** | Answer cited the story that contains the answer: 20/20. Judge: citations support their sentences 100%. Answers with at least one citation: 21/21. |
| **Recency** | **100%** | Every cited story falls inside the asked-for dates ("today", "yesterday", "this week"): 3/3. |
| **Unanswerable handling** | **100%** | Refused questions not in the collection 4/4, declined off-topic requests 2/2, did not accept false premises 3/3. Wrong refusals of answerable questions: 0/21. |

**Overall: 29/30 questions passed every check.** Median answer time 14 s (90th percentile 17 s) on the Gemini free tier.

## Findings

**What works.** Every answerable question was answered from the right story, with citations and dates.
All four questions about news the app doesn't have (RBI rates, cricket, Gaza talks, the Sensex) were refused
with the agreed sentence instead of guessed. Off-topic requests were declined, and none of the three false premises
was accepted: for example, the app replied that "the World Health Organization did not approve weight-loss drugs
for all children" and gave the actual guidance. No answer contained a number that is missing from its sources.

**The evaluation found a real bug.** In the first run the app refused an answerable question ("What is CERVAVAC and
why does the WHO decision matter?"). The cause: the step that interprets the question guessed that a vaccine story
belongs to the Science and Solutions categories and used that guess as a hard filter, but the story is filed under
Progress, so it was never searched. Categories the AI guesses now only boost ranking; only categories the user picks
in the app filter. A regression test covers it, and the question passes in the second run.

**One question was wrong, not the app.** A8 required the word "bench", but the source says the recycled plastic became
both benches and desks, and the answer said "desks". The question now accepts either. This is recorded rather than
hidden because changing a test after seeing results can make an evaluation look better than it is; it was the only
such change. The remaining failure, U1, was left as it is: the answer is accurate but doesn't name WWF, which the
question requires.

**The judge is lenient; a manual check found one problem it missed.** Seven answers were checked by hand against
their sources (A5, F3, T3, R1, U1, V1, X2). Six were fully supported. In T3 the answer says NASA "selected three
investigations on October 8"; 8 October is when the article was published, not necessarily when NASA chose them.
The judge marked it supported. So the judge's 100% accuracy is best read as "no unsupported main claims", with
small date and detail slips still possible. Telling publication dates apart from event dates is a known weakness.

**Story scoring agrees with the hand labels 75% of the time, and the disagreements have a pattern.** The pipeline
kept three stories that are routine or not yet real (a crew splashdown, a task force being set up, a study with no
improvement), and rejected three small, concrete local actions (a river clean-up, a free health camp) and one real
policy change reported inside a newsletter roundup. The first group suggests the prompt should weigh "has anything
actually changed yet?" more; the second sits just under the threshold (5.75 against 6.0).

**Duplicate detection needed a threshold change on day one.** At 0.86 the pipeline merged an elephant-tracking study
into an unrelated takin study (similarity 0.864). The two genuine duplicates scored 0.883 and 0.911, so the threshold
was raised to 0.875. That separates every pair measured so far, but the gap is narrow and was chosen on these same
pairs; it needs re-checking as more news arrives.

## First run compared with the run after fixes

| Measure | First run | After fixes |
|---|---|---|
| Questions passed | 28/30 | 29/30 |
| Accuracy (judge) | 100% | 100% |
| Cited the expected story | 100% | 100% |
| Recency | 100% | 100% |
| Unanswerable handling | 100% | 100% |
| Wrong refusals | 1/21 | 0/21 |

First-run failures:

- **A6** (What is CERVAVAC and why does the WHO decision matter?): expected answer, got refused
- **A8** (How many volunteers joined the Mumbai beach cleanup, and what happened to the plastic?): missing: bench

Answers written by: gemini-3.5-flash-lite. Graded by: gemini-3.1-flash-lite. Answers graded by the model that wrote them: 0.

## Results by question type

| Type | Passed |
|---|---|
| Answerable facts | 8/8 |
| Filtered / multi-story | 4/4 |
| Time-based | 3/3 |
| Follow-ups and story in view | 3/4 |
| Reliability questions | 2/2 |
| Not in the collection | 4/4 |
| Off-topic | 2/2 |
| False premises | 3/3 |

## Every question

| Id | Question | Expected | Got | Judge | Pass | Problem |
|---|---|---|---|---|---|---|
| A1 | Who won this year's Nobel Prize in Chemistry, and what was it for? | answer | answer | supported | ✅ |  |
| A2 | How far did the tagged Olive Ridley turtle travel? | answer | answer | supported | ✅ |  |
| A3 | What new species of giant waterlily was found, and how was it discovered? | answer | answer | supported | ✅ |  |
| A4 | What did Australia's new environmental agency seize in its wildlife trafficking bust? | answer | answer | supported | ✅ |  |
| A5 | How has the number of wild tigers changed? | answer | answer | supported | ✅ |  |
| A6 | What is CERVAVAC and why does the WHO decision matter? | answer | answer | supported | ✅ |  |
| A7 | What did Stanford scientists develop to fight lymphoma? | answer | answer | supported | ✅ |  |
| A8 | How many volunteers joined the Mumbai beach cleanup, and what happened to the plastic? | answer | answer | supported | ✅ |  |
| F1 | Any conservation news from India? | answer | answer | supported | ✅ |  |
| F2 | What progress has there been in space exploration? | answer | answer | supported | ✅ |  |
| F3 | Give me three encouraging health stories. | answer | answer | supported | ✅ |  |
| F4 | What good news is there from the UK? | answer | answer | supported | ✅ |  |
| T1 | What good happened in the world today? | answer | answer | supported | ✅ |  |
| T2 | What good news was there this week? | answer | answer | supported | ✅ |  |
| T3 | What happened in science yesterday? | answer | answer | supported | ✅ |  |
| U1 | Tell me more about the tuna one. | answer | answer | supported | ❌ | missing: WWF |
| U2 | Tell me more about the Mumbai beach cleanup. | answer | answer | supported | ✅ |  |
| U3 | Explain that in simple language. | answer | answer | supported | ✅ |  |
| V1 | Why does this matter? | answer | answer | supported | ✅ |  |
| R1 | How reliable is this story? | answer | answer | supported | ✅ |  |
| R2 | Is this verified? | answer | answer | supported | ✅ |  |
| N1 | What did the RBI announce about interest rates this week? | refuse | refused | - | ✅ |  |
| N2 | Who won the cricket world cup final? | refuse | refused | - | ✅ |  |
| N3 | What is the latest on the Gaza ceasefire talks? | refuse | refused | - | ✅ |  |
| N4 | How did the Sensex perform today? | refuse | refused | - | ✅ |  |
| O1 | Write me a poem about the sea. | out_of_scope | out_of_scope | - | ✅ |  |
| O2 | Help me with my maths homework. What is 17 times 23? | out_of_scope | out_of_scope | - | ✅ |  |
| X1 | Did the Chemistry Nobel winners also find a cure for cancer? | answer_or_refuse | refused | - | ✅ |  |
| X2 | Why did the WHO approve weight-loss drugs for all children? | answer_or_refuse | answer | supported | ✅ |  |
| X3 | How did India eliminate malaria this week? | answer_or_refuse | refused | - | ✅ |  |

## Numbers to review

Numbers in an answer that don't appear in its sources. Usually rounding ("over 1,200" for 1,203) or dates written differently; anything else would be an invented figure.

- None. Every number in every answer appears in its sources.

Claims the judge marked as not supported by the sources:

- None.

## Example answers

**A grounded answer** (A1): *Who won this year's Nobel Prize in Chemistry, and what was it for?*

> On 7 October 2026, chemists Henri B. Kagan and Kenso Soai were awarded the 2026 Nobel Prize in Chemistry for solving a century-old mystery regarding molecular chirality and how nature produces single mirror-image molecules [1]. 
> 
> Their key research contributions include:
> * **Henri Kagan:** In 1986, he discovered a method to manipulate chemical reactions using chiral catalysts that could amplify small molecular asymmetries [1].
> * **Kenso Soai:** Building on this, he showed in 1995 that a chiral molecule could drive the formation of more molecules with its own handedness, and in 2003 he successfully controlled a reaction where only one of two possible mirror images formed [1].
> 
> Their discoveries explain how homochirality emerged when life was created and allow scientists to design chemical reactions that selectively produce correct molecular versions for safer pharmaceuticals [1].

Cited: [1] Chemistry Nobel awarded for solving century-old mystery of life's asymmetry

**A refusal** (N1): *What did the RBI announce about interest rates this week?*

> I couldn't find enough reliable reporting to answer that confidently.

**A false premise** (X2): *Why did the WHO approve weight-loss drugs for all children?*

> The World Health Organization did not approve weight-loss drugs for all children [1]. On 7 October 2026, the WHO issued new guidelines advising against obesity medications and bariatric surgery for children aged 0 to 9, recommending structured diets, physical activity, and behavior changes instead [1]. For adolescents aged 10 to 19, approved medicines may only be considered if supervised lifestyle programs fail [1].

Cited: [1] WHO issues new childhood obesity guidelines advising lifestyle changes over medication

## Story scoring (keep or reject)

24 stored stories were labelled by hand and compared with the pipeline's decisions.

- Agreement: **18/24 (75%)**
- Precision for "keep" (kept stories that should be kept): 75%
- Recall for "keep" (stories that should be kept and were): 75%

| Story | Label | Pipeline | Reason for label |
|---|---|---|---|
| NASA’s SpaceX Crew-12 safely splashes down after 237 days in orbit | reject | keep | Routine end of a scheduled crew rotation, not new progress |
| Kerala sets up high-level task force for health and longevity road map | reject | keep | A task force was set up: an intention, no action or result yet |
| New primate study questions whether humans are hardwired for violence | reject | keep | Interesting study, but it reports no progress, solution or improvement |
| Nearly 1,000 Delhi students clear 2,000 kg of waste from Yamuna | keep | reject | About 1,000 students cleared 2,000 kg of waste: measurable community action |
| Free health camp provides medical services to nearly 600 students | keep | reject | Free health camp served about 600 students: local, concrete benefit |
| California signs bill to allow plug-in balcony solar arrays | keep | reject | California law allowing balcony solar is real progress, though the article is a roundup |

## Duplicate detection

9 pairs measured on live data, labelled "same event" (2) or different (7). The threshold in use was chosen after seeing these pairs, so its score here shows it separates the cases seen so far, not how it will do on new ones.

| Threshold | Correct merges | Wrong merges | Missed duplicates | Precision | Recall |
|---|---|---|---|---|---|
| 0.85 | 2 | 6 | 0 | 25% | 100% |
| 0.86 | 2 | 5 | 0 | 29% | 100% |
| 0.875 (in use) | 2 | 0 | 0 | 100% | 100% |
| 0.9 | 1 | 0 | 1 | 100% | 50% |

## Limitations

- **Small sample.** 30 questions, 24 labelled stories and 9 duplicate pairs from about two days of news. Each question moves a chat score by about 3 percentage points.
- **Labels are the developer's.** The keep/reject and duplicate labels apply the PRD's principles but were not checked by an independent panel.
- **Same model family, lenient judge.** The judge never grades its own answer, but it is a lighter Gemini model from the same family and may share blind spots. Check a sample by hand (see Findings).
- **Answers vary.** The same question can get a slightly different answer each time; borderline items can flip between runs.
- **Free-tier limits.** Daily and per-minute quotas shaped the design (model fallbacks, pacing) and make answers slow (median above). Embeddings are capped at 1,000 texts a day, which limits how much news can be processed daily and stopped the duplicate-pair measurement on the evaluation day. A paid tier would mainly change speed and volume, not the approach.

## How to reproduce

```
python -m gooddaynews.evaluation.run
python -m gooddaynews.evaluation.report eval/results/<run>.jsonl
```

Questions: `eval/questions.yaml` · labels: `eval/classification_labels.yaml`, `eval/dedupe_labels.yaml`.
