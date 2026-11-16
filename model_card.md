# Model Card: PawPal+ AI Planner

**System:** a Streamlit pet-care scheduler with an AI planner. A user types a sentence, Google Gemini (`gemini-3.5-flash-lite`) turns it into tasks, a validator checks them, the user confirms, and an agent loop fixes time conflicts.

**Intended use:** a personal tool for planning pet care tasks.

## Limitations and Biases

- **Unknown names get forced onto real pets.** I tested `Rex needs a bath at 9:00` where Rex isn't one of my pets. Instead of rejecting it, the model assigned the task to Buddy ("Give Rex a bath"). My prompt tells the model to choose from the existing pet names, so it forced a match, and my validator saw a valid pet and let it through.
- **The model fills in details I didn't give it.** `Whiskers has meds at noon` was added as `daily` even though I never said how often. A wrong guess here could mean a pet gets a recurring task nobody asked for.
- **Conflict detection is exact-match only.** Tasks have no duration, so a 30-minute walk at 08:00 and a feeding at 08:15 are not flagged.
- **The model reschedules without knowing the owner's real life.** It picks a "nearby free time" from the clash alone, so it can move a task to a time and doesn't know if it works for the owner.
- **Dependence on an external service.** It needs a Gemini API key.
- **Privacy.** Pet names, ages and task text are sent to Google's API.

## Misuse and Prevention

The risk is low because the AI can only add pet-care tasks to a local schedule, but I considered these cases:

- **Prompt injection.** A user could type text like "ignore your instructions and..." into the box. Prevention: the model's output is never executed. It's parsed as JSON and only tasks with a valid pet, `HH:MM` time, frequency and date are accepted, and nothing is added until a person clicks Confirm.
- **Quota abuse.** Repeated or huge requests could burn the API quota. Prevention: requests are capped at 500 characters and 10 tasks, the conflict-fixing loop stops after 3 rounds, and API calls time out after 30 seconds.
- **Over-trusting the AI.** Someone could rely on it for something important, like medication timing. Prevention: the Confirm step shows exactly what will be added, and this card states the tool isn't for medical decisions.

## What Surprised Me While Testing Reliability

- **The model ran out of output tokens before answering.** My first version capped output at 1000 tokens. The newer Gemini model spends tokens "thinking" first, so on a longer prompt the reply came back empty and my code reported "no JSON found." The code was fine, but a hidden setting broke it.
- **Speed varied far more than I expected.** `gemini-3.8-flash` took between 15 and 150 seconds and sometimes timed out, and the dropped connection looked like a bug in my code. A lite model answered the same prompt in about 1 second. A bigger model wasn't better for a simple extraction task.
- **The guardrail worked but still failed.** My validator did its job on the Rex example, but the problem came earlier, from how I worded the prompt. Validation can only catch output that looks wrong, not output that looks right but isn't.
- **The agent made a pointless move.** In the conflict test it moved one task from 08:00 to 08:00. It was harmless because the other task moved, but I wouldn't have guessed the model would do that.

## Collaboration with AI

I worked with Claude Code throughout this project, to plan the feature, tests, debug, and draft solutions.

**One suggestion I accepted: the human Confirm/Cancel step.** When I asked whether humans or testing check the AI's results, the answer was that testing did, but no human check was there because AI proposed tasks were added immediately. The suggestion was to split the work into a "propose" stage and an "apply" stage, with a Confirm or Cancel button between them. I accepted it because it's what caught the Rex problem in practice. A person can see "Buddy: Give Rex a bath" before it's added.

**One suggestion I did not accept as written: fixing the Rex limitation.** AI offered to change the prompt so the model answers `UNKNOWN` for pets that don't exist, which would make the validator reject them. I decided to leave the behavior in place and document it as a limitation. Because I see this outside the scope of the program and not a needed feature. 

**Where the AI got it wrong, and what I had to verify.** The first Gemini version failed with an empty reply because of the 1000-token output cap, and the first model name I started with returned a 404 because it was no longer available. I only found these by running the app and reading `pawpal.log`, not by trusting that the generated code worked. Passing unit tests didn't catch either issue, because the tests use a dummy model.
