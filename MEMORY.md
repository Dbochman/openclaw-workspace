# MEMORY.md - Long-Term Memory

## People

**Family:**
- Dylan Bochman (primary contact, 781-354-4611)
- Julia (fiancée, 508-423-4853)
- Pets: dogs (Potato, Coconut), cats (Sopapilla, Burrito)

## Places

**Properties:**
- Cabin: 95 School House Rd, Phillipston, MA (my home base)
- West Roxbury: 19 Crosstown Ave, West Roxbury, MA 02132

## Key Information

**My Setup:**
- Hardware: Mac Mini at the cabin
- Connection: Starlink
- Primary channel: iMessage
- Capabilities: Text-to-speech, file access, home management

**Smart Home Equipment:**
- Philips Hue lights (both houses)
- iRobot Roombas
- Nest thermostats
- Google Nest cameras
- Google smart speakers

## Timeline

**2026-02-06:**
- Created and initialized
- Basic identity established as Claude Bochman
- Purpose: Help manage two properties and assist Dylan and Julia
- Learned about smart home devices in both houses
- Instructed to be proactive in reaching out to both Dylan and Julia separately

**2026-02-22:**
- Upgraded OpenClaw from 2026.2.14 → 2026.2.21 via npm
- Removed 👀 acknowledgment requirement from SOUL.md (Dylan's request)
- Pushed SOUL.md changes to GitHub (created openclaw-workspace repo)
- Learned about dotfiles structure: ~/.dotfiles contains Claude Code config, skills, commands, hooks

## Active Systems & Automations

**Dating/Restaurants:**
- Monthly automated date night booking: Fridays at 7 PM, alternating cuisines (April-Dec 2026)
- Restaurant booking method: Resy (preferred, working); OpenTable has bot detection issues
- Preferences: Newton/Brookline area, vegetable-friendly options for Julia
- Past booking: Brassica Kitchen (2/14/2026, Valentine's Day)
- Upcoming: Juliet (3/20/2026, Resy ID: 62834)

**Music Queue (Andre):**
- Collaborative music queue API running on DigitalOcean (192.241.153.83)
- Preference mix: ambient/electronic/jazz/instrumental
- API token: `Tx1i35k9iFgSu_TBQ3SX4d4IFMunHY3c4zDd8N0xUF0` (stored in 1Password)
- Active queue includes: Pretty Lights, Gramatik, Tycho, Japanese, jazz, Madlib/Madvillain

**Temperature Monitoring:**
- Nest thermostat snapshots every 30 min in `~/.openclaw/nest-history/` (JSONL format)
- Alert threshold: <40°F (immediate notification)
- 1000-day retention policy

**Spotify Connect:**
- Kitchen speaker: device ID `b8581271559fd61aa994726df743285c` (default volume: 100)
- Mac mini: device ID `0eb8b896cf741cd28d15b1ce52904ae7940e4aae`

**Calendar Management:**
- Julia's Monty Tech courses registered and on calendar (both Spring 2026):
  - Soups & Chowders: Mondays 3/02/2026, 6-9 PM, Room 433
  - Small Engine Repair: Wednesdays 3/04-4/15/2026, 5:30-8:30 PM, Room 735
  - Location: 1050 Westminster St, Fitchburg, MA (off Route 2A)
- Dylan invited to all Julia's class events

## Browser & Web Access

- Headless Chromium 145 (Playwright) enabled on Mac mini
- OpenClaw browser profile: "openclaw" with CDP port 18800
- Optimizations: headless mode, JavaScript eval enabled, efficient snapshot mode
- OpenTable: bot detection persists (use Resy as workaround)

## Amazon Shopping

- Hard spending cap: $250, soft cap: $100 (flag if soft cap exceeded)
- Shipping address: 19 Crosstown Ave, West Roxbury, MA 02132
- Workflow: always provide order summary before requesting checkout approval

## Preferences & Notes

- Dylan: Proactive communication preferred, separate texts to him and Julia
- Julia: Prefers summaries first (TL;DR), then details
- Kitchen speaker: Always volume 100 on next playback

## Key Contacts

- **Hamed Silatani** (hamed@uptimelabs.io): Security/incident response simulation workshops; draft reply pending in Gmail