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
