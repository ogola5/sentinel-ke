# UI / UX Test Flow

Last updated: 2026-03-26

Use this as the manual browser script to test whether Sentinel-KE flows correctly for a judge, analyst, or operator. The goal is not only to see screens render, but to confirm that each click leads to the intended next action without confusion, dead ends, blank states, or misleading metrics.

## Preflight

Before testing:

1. Open the hub UI at `http://localhost:3000`.
2. Sign in with a central user account.
3. Keep one tab open on the main UI and one tab ready for API checks if needed.

Basic pass condition:

- the app loads
- login succeeds
- top navigation is visible
- there are no blank panels, endless spinners, or browser errors

## Flow 1: Executive / Judge Path

This is the most important flow. It should feel deliberate, calm, and evidence-led.

### Step 1: Command

Click:

- sign in
- land on `Command`

Expect:

- heading `National Command Centre`
- executive brief visible near the top
- readiness / AI evidence cards visible
- no raw debug output shown as the primary story

Pass if:

- the screen explains posture fast
- the top fold feels like one briefing, not many equal-weight widgets

Fail if:

- the screen feels noisy
- key numbers are missing
- the top cards contradict each other

### Step 2: Executive Brief

Click:

- stay on the top fold of `Command`

Expect:

- one judge-facing summary
- lane-separated evidence for cyber and corruption
- scientific evidence state shown clearly
- live counts shown as live counts, not training counts

Pass if:

- you can explain the platform in under 20 seconds from this fold
- the cards distinguish operational truth from scientific truth

Fail if:

- the brief mixes baseline, live predictions, and training labels into one number

### Step 3: GNN Intelligence

Click:

- `Open GNN Intelligence`

Expect:

- heading `GNN Intelligence Hub`
- a clear lane breakdown
- the panel `Operational truth vs scientific truth`
- reasoned AI evidence, not only charts

Pass if:

- you can point to what is operationally strong and what is still scientifically caveated

Fail if:

- the screen only shows model numbers with no context
- the lane caveats disappear

### Step 4: Investigate

Click:

- `S3 Investigate` or the investigation action from command / GNN

Expect:

- heading `Entity Investigation`
- one entity-focused case view
- risk summary
- reason codes / evidence path
- next actions visible

Pass if:

- the page answers: what is risky, why, what do I do next

Fail if:

- it feels like a raw database record instead of a briefing

### Step 5: Federation

Click:

- open `System`
- click `Federation`

Expect:

- heading `Federation Network`
- partner / sync status
- privacy-preserving coordination language
- no raw partner data leakage

Pass if:

- the page clearly says what is shared and what stays local

Fail if:

- it looks like all agency data is centrally exposed

### Step 6: Corruption

Click:

- from `Operations` or `System`, open `Corruption Intelligence`

Expect:

- heading `Corruption Intelligence`
- procurement / supplier / contract story
- graph-risk framing, not legal-proof framing

Pass if:

- the user can see how corruption patterns emerge across relationships

Fail if:

- the page sounds like the model is convicting people

## Flow 2: Analyst Path

This checks that the app works as an investigation workspace, not just a demo fold.

### Step 1: Live Feed

Click:

- `Live Feed`

Expect:

- heading `National Live Feed`
- event cards or a live list
- obvious click target into detail

Pass if:

- clicking the first event opens detail without confusion

### Step 2: Event Detail

Click:

- first event in the list

Expect:

- detail panel opens
- event hash or evidence reference is visible
- the event can lead to entity or campaign work

Pass if:

- the analyst can move from event to case-building

### Step 3: Threat Graph

Click:

- `Threat Graph`

Expect:

- heading `Threat Graph Explorer`
- graph view or graph summary
- counts / entity classes visible

Pass if:

- it helps explain relationships

Fail if:

- it is only decorative

### Step 4: Campaigns

Click:

- `Campaigns`

Expect:

- heading `Campaigns`
- grouped operations or campaigns visible
- action such as case generation available

Pass if:

- you can explain how separate alerts become one operation

## Flow 3: Operator Response Path

This checks whether containment feels real and traceable.

### Step 1: Defense

Click:

- `Defense`

Expect:

- defense action surface
- current action types visible
- backend-driven options, not dead hardcoded buttons

Pass if:

- actions look tied to evidence and policy

### Step 2: Action History

Click:

- stay on defense history / recent action area

Expect:

- persisted history rows
- status fields like executed, skipped, failed, or no integration

Pass if:

- history survives refresh

Fail if:

- history disappears because it only lived in the browser session

## Flow 4: Report Path

This checks whether the story can be packaged cleanly.

### Step 1: Reports

Click:

- `Reports`

Expect:

- heading `Operational Reports`
- report types relevant to the user role

Pass if:

- you can create a report from an operational object

### Step 2: Preview and Download

Click:

- `Preview JSON`
- `Download report`

Expect:

- preview shows a compact summary
- download triggers successfully

Pass if:

- the report is clearly tied to an entity, prediction, or campaign

## Flow 5: Edge Agency Path

Use this only when testing the edge stack at `http://localhost:13000`.

### Step 1: Edge Command

Click:

- sign in on edge
- land on `Command`

Expect:

- command view loads
- local agency framing is visible

### Step 2: Edge GNN

Click:

- `Open GNN Intelligence`

Expect:

- local scoring language
- not central-hub language

### Step 3: Edge Investigation

Click:

- `S3 Investigate`

Expect:

- local entity investigation works

### Step 4: Edge Federation

Click:

- `System`
- `Federation`

Expect:

- `Federation Network`
- local sync state
- partner id / sync health

Pass if:

- it is obvious that raw telemetry stays local and only warnings sync outward

## Quick Scorecard

Use this after one full run:

- `Command` explains the product in one screen
- `GNN Intelligence` separates operational truth from scientific truth
- `Investigation` explains risk, evidence, and next action
- `Federation` explains privacy and coordination clearly
- `Corruption Intelligence` explains pattern risk without overclaiming legal proof
- `Defense` shows real action choices and persisted history
- `Reports` previews and downloads correctly
- no screen has a dead button, broken action, or blank state

## What “Good Flow” Feels Like

The UI/UX is working if:

- every screen answers one main question
- every major click has a visible result
- the next step is obvious
- the system feels evidence-led, not dashboard-led
- judges can follow the narrative without you rescuing the UI verbally

The UI/UX is not working if:

- users keep asking where to click next
- numbers are shown without meaning
- screens look technically rich but operationally vague
- the story only makes sense when you explain around the interface
