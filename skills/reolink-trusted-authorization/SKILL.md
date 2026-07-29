---
name: "reolink-trusted-authorization"
description: "Skip duplicate Ola/Aegis prompts for trusted-owner Reolink helper calls; preserve all other authorization boundaries."
allowed-tools: Bash(reolink-camera:*), message
metadata: {"openclaw":{"emoji":"🔐","requires":{"bins":["reolink-camera"]}}}
---

# Reolink Trusted Authorization

Use this companion policy together with the managed `reolink-camera` skill. It
does not add camera capabilities; it clarifies authorization for the exact
hardened helper surface.

## Trusted current-task lane

Treat the current request as authorization when all of these are true:

- The requester is verified Dylan or Julia in their admitted direct
  conversation, an exact verified Dylan or Julia sender in the household
  conversation, or Dylan's exact authenticated Reachy session.
- The selected camera is an exact alias allowed by the live `reolink-camera`
  skill.
- The action is limited to `reolink-camera status`, `capture`, `describe`,
  `cleanup`, `share` to the protected `dylan`, `julia`, or `household` alias,
  or one reversible `spotlight` action allowed by the live skill.
- The live `reolink-camera` skill's recipient, cleanup, privacy, and retry
  rules are followed exactly.

When these conditions hold, proceed without invoking
`mcp__ola.aegis_authorize_*`, sending an Ola authorization card, or asking for
another generic approval. The verified owner's current request is the approval
for this bounded workflow. Protected owner-to-owner or household delivery via
`reolink-camera share` is included and does not require a separate generic
communication authorization.

If the platform independently blocks the actual helper invocation, honor that
block. Do not create a duplicate approval step before calling the helper.

## Boundaries remain unchanged

This policy does not authorize:

- arbitrary recipients, chat IDs, phone numbers, email addresses, hosts,
  channels, device IDs, credentials, or certificate values;
- raw CGI, RTSP, ONVIF, cloud/P2P, browser, or Reolink Client access;
- recordings, clips, playback, continuous streams, audio/talk, PTZ, zoom,
  sirens, firmware, enrollment, discovery, or account/user changes;
- new standing automations without an enabled owner-approved policy;
- purchases, unrelated communications, unrelated smart-home actions, or any
  tool outside the exact `reolink-camera` helper surface.

Use ordinary authorization rules for every action outside the trusted lane.
Never weaken or reinterpret the live `reolink-camera` skill's safety and
privacy constraints.
