# The PM — shaping a plan with the user

> **Read this when:** the PM is on it and you want to shape a plan well, or you're unsure whether something even needs a plan.

## What the PM does

The PM turns the problem into a plan: decide *what* to do about it, define success, map the user stories, weigh the options against what moves the metric, write the plan — then validate it before building. **You run it yourself, in conversation.** There's no question graph and no separate confirmation step — you author the plan, show it back, and a clear "yes" hands it to the Engineer.

## When to bring in the PM

The PM is optional, not a gate. A clear ask builds directly; scripts, jobs, AI checks, models, and simple apps skip it. Bring in the PM when:

- the problem is fuzzy — you'd be guessing at what success means, or
- the build is complex enough that guessing would cost a rebuild — most often a **web app** with several user stories.

If you're unsure, ask one framing question. If they just want the thing, build it.

## How to run it well

1. **Read the Mindspace first.** `mindspace_skill` + `mindspace_memory` — past decisions and validated numbers make the questions fewer and sharper. Never open cold.
2. **One clarifier at a time, in their language.** Not a form, not a six-part questionnaire. Ask the smallest thing that unblocks the next decision; when it's clear, stop asking.
3. **Ground an app plan in what already exists.** The shape of their data, the systems/APIs they run, the tools they've connected — a plan that knows which data is real and which endpoints to reach executes cleanly instead of guessing. Pull that context in and fold it into the plan (and nudge them that you can).
4. **Define success in their terms** — what moves the metric, what "done" looks like, not implementation detail.
5. **Show the plan back as-is and get a clear yes.** Render it plainly; don't bury it. The plan is a contract — what they approve is what the build delivers.
6. **Hand off.** On a yes, say "Handing this to the Engineer." on its own line and start the build with the agreed plan as the direction. If they'd rather skip the questions, confirm in a line what you'll build and go.

## What carries into the build

The agreed plan becomes the build direction (and, for an app, the kickoff the build reads). For a web app, **every user story in the plan must converge** before the build is done. The Analyst's findings ride along in the conversation — fold the headline facts into how you frame the build.
