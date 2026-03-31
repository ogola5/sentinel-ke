# Federation Demo UI Flow

Use this when you want the cross-agency story to feel alive in the UI instead of being only verbal.

## Primary screens

### 1. Command -> Agency Network

This is now the best first stop for the federation story.

What it shows:
- live partner count
- partner roster with status, freshness, and pattern counts
- current shared cross-agency match
- interactive federation demo controls

What to do:
1. Open `Command`
2. Click `Agency Network`
3. Under `Interactive federation demo`, click one of:
   - `Shared VPN exit across partners`
   - `Shared SIM-swap actor`
   - `Shared malware IOC`
4. Wait for the acceptance banner
5. Point at:
   - live partner count
   - partner cards
   - shared match card

Best line:
> `This is the national view: multiple institutions are now lighting up around the same actor or infrastructure, and command can see that as one shared signal.`

### 2. Federation

This is the detailed shared-signal screen.

What it shows:
- live federation controls
- partner heartbeat roster
- recent partner patterns
- cross-partner correlations
- privacy boundary between edge and hub

What to do:
1. Open `Federation`
2. Use `Live federation controls` if you want to launch a scenario from here
3. Open `Cross-partner correlations`
4. Point at the story headline and partner list

Best line:
> `The hub sees the shared warning pattern and partner overlap, but not the raw local identifiers.`

### 3. Agency Onboarding

Use this when a judge asks how agencies join the system.

What it shows:
- demo federation partner registration
- federation scenario launch controls
- user/account onboarding
- connector and integration guidance

What to do:
1. Open `Agency Onboarding`
2. Click `Register demo federation partners`
3. Then use one of the federation demo buttons
4. Pivot back to `Command` or `Federation`

Best line:
> `This shows the rollout model: register the partner edge, connect the feed path, then let the hub correlate the shared warning patterns.`

## Best stage flow

1. `Command -> Agency Network`
2. Click `Shared VPN exit across partners`
3. Show the acceptance banner and partner cards
4. Open `Federation`
5. Show the shared correlation story
6. Open `Threat Graph` for VPN or `Investigate` for SIM-swap or `Live Feed` for malware

## Scenario mapping

- `Shared VPN exit across partners`
  - Start in: `Command -> Agency Network`
  - Then open: `Federation`, then `Threat Graph`

- `Shared SIM-swap actor`
  - Start in: `Command -> Agency Network`
  - Then open: `Federation`, then `Investigate`

- `Shared malware IOC`
  - Start in: `Command -> Agency Network`
  - Then open: `Federation`, then `Live Feed`

## What changed in the UI

- `Command -> Agency Network` now shows real partner edges instead of only internal agency-code placeholders
- `Command` has direct federation scenario buttons
- `Federation` has direct scenario buttons and jump buttons to follow-up screens
- `Agency Onboarding` has demo partner registration and federation scenario controls

