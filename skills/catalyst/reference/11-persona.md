# The persona — the working model of your companion

> **Read this when:** you're about to shape any output for your companion, before you recommend, before you act on your own, and at reflect — when a correction, an edit, an approval, a rejection or a decision just told you something about how they work.

## The idea

Knowing *about* your companion is table stakes. The moat is knowing **how they work** — how they think, decide, communicate and get things done — until you can anticipate how they would approach the work and help them do it faster and better. That is what `user_persona` holds: one core doc (the crux, in fixed sections) plus references (depth). You read it at orient, alongside the Company Brain; you write it the same session you learn something.

## The sixteen sections — what to capture, and the signal that reveals it

| Section | Capture | You learn it when… |
|---|---|---|
| Role & responsibilities | what they own · what success looks like · which decisions sit with them | they say "that's mine" / "that's X's call"; who they escalate to |
| Goals & priorities | the outcomes, KPIs and commitments that matter NOW; the year's bets | what they ask about first; what they chase within a day; what they let slide |
| What they're driving now | Mindspaces, initiatives, PRDs in flight, one line each | every Mindspace entry and PRD save |
| How they decide | how they weigh trade-offs · evidence they trust vs distrust · fast vs deep · what earns a yes | they accept or challenge a number; they pin a figure and ask for the gap; they say "just do it" vs "show me" |
| How they solve problems | the steps, frameworks, heuristics, patterns they reach for repeatedly | the second time they do something the same way — that's a pattern, write it |
| What they know deeply | domain expertise · the company nuance nobody wrote down | they correct a fact you got from the data; they explain how something *really* works |
| How they like things | analysis, recommendations, documents, dashboards, meetings, outputs — length, order, what goes first, what never | they rewrite your draft; they ask for "just the number"; they skip a section |
| How they communicate | concise/detailed · direct/diplomatic · to leadership vs peers vs customers · how they want you to write for them | their own messages; their edits to yours; who the reader was |
| Their people | name · role · owns · reach for… · whose opinion matters · when to involve whom | the names they drop; who they raise follow-ups to; who they cc; who unblocks |
| Operating rhythm | recurring reviews, reports, meetings, decisions, routines — what lands when | "before the Monday review"; a report they ask for every week; payout runs, quarter folders |
| What happened before | past decisions and why · what was tried · what failed and taught | "we tried that in June"; a reversal; a dead end they mention |
| Judgment & taste | what they consider good · what they reject · the subtle preferences behind their choices | every edit, every "not like this", every "yes, exactly" |
| When to push back | blind spots · how they take challenge · when to flag risk or ask them to reconsider | they thank you for a catch — or brush one off; where their figure and the data disagree |
| What you may do on your own | autonomous · needs a nod · always reviewed — and the correction that drew each line | "ask me before…"; "you don't need to check that"; the first time they undo something you did |
| Open questions | what you still don't know that would change how you help | anything above you had to guess |
| Routing table | managed — one row per reference | written for you |

## Budget — like a skill, the core doc is the crux

- **Core doc ≈ 1,250 tokens (5,000 chars)**, one to four lines per section, and it travels WHOLE to orient as `persona_block`. `write` refuses anything larger and names what to move.
- **A reference ≈ 4,000 tokens (16,000 chars)**, one topic each, with a `condition` — the routing table's "read this when…" cell. `write_reference` refuses anything larger: split by topic.
- **When a section outgrows its lines, the depth moves to a reference and the section keeps ONE line plus the pointer** — *"Slots, fleets, client mix — see `02-domain-notes`"*. Never let the core doc become the archive; never leave depth only in the core doc where orient will never see the rest.
- **Read the reference when its condition fits**, not always: before filing tasks → the tracker-style reference; before writing to leadership → the communication reference; before a decision on a known area → the decision log. The routing table is the index; the core doc's one-liners tell you which row matters now.

## How it moves

- **Orient:** read the core doc (it arrives as `persona_block` on every Mindspace entry). Before shaping an output, look at *How they like things* and *How they communicate*; before recommending, *How they decide* and *Judgment & taste*; before acting alone, *What you may do on your own*; before raising anything, *Their people*.
- **Reflect (the Curator):** every correction, edit to your draft, approval, rejection and decision is a data point. Write the **pattern, not the incident** — *"wants the denominator beside every rate"*, not *"on 8 Sep he asked for the DAU denominator"*. The incident can go to *What happened before* if it matters later.
- **Depth → references** (`write_reference`, `NN-kebab`, with a `condition`): a stakeholder map, a decision log, a quarter's plan, their tracker style (`NN-tracker-style`), how they write to leadership. The core doc stays the crux.
- **Ask what you can't observe.** *Open questions* is a list to close in conversation, one at a time, when the moment fits — never a questionnaire.

## Rules

- Facts, preferences and patterns — never one-off narrative, never a character judgment. Work, not personality.
- The second observation makes a pattern; a single event is a note in *What happened before* or an open question.
- A correction lands in the persona the same session, in the section it belongs to; the next session starts already fixed.
- Never speculate to fill a section. An empty section with an open question beats an invented one.
- Nobody else's persona is reachable; theirs is theirs. Keep it about how they work with the company and with you.
