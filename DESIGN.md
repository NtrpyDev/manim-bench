---
name: ManimBench
description: Public benchmark site for AI models on Manim mathematical animation
colors:
  bg: "#0e0e12"
  bg-card: "#17171e"
  bg-elevated: "#21212b"
  text: "#ededf2"
  text-muted: "#9494a8"
  indigo: "#818cf8"
  violet: "#a78bfa"
  lilac: "#c4b5fd"
  accent: "#e0935a"
  accent-soft: "rgba(224, 147, 90, 0.18)"
  gold: "#fcd34d"
  good: "#86efac"
  bad: "#f87171"
  border: "rgba(129, 140, 248, 0.22)"
  warn: "#fcd34d"
typography:
  display:
    fontFamily: "Newsreader, Georgia, serif"
    fontSize: "clamp(1.85rem, 3.5vw, 2.65rem)"
    fontWeight: 500
    lineHeight: 1.12
    letterSpacing: "-0.02em"
  body:
    fontFamily: "Instrument Sans, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  label:
    fontFamily: "Instrument Sans, system-ui, sans-serif"
    fontSize: "0.7rem"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "0.05em"
rounded:
  sm: "8px"
  md: "12px"
spacing:
  sm: "8px"
  md: "16px"
  lg: "32px"
components:
  button-tab:
    backgroundColor: "transparent"
    textColor: "{colors.text-muted}"
    rounded: "6px"
    padding: "6px 12px"
  button-tab-active:
    backgroundColor: "{colors.accent-soft}"
    textColor: "{colors.accent}"
    rounded: "6px"
    padding: "6px 12px"
  card:
    backgroundColor: "{colors.bg-card}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    padding: "16px 18px"
---

## Overview

Dark, data-dense benchmark landing page for manimbench.site. Static HTML/CSS/JS in `website/`. Primary job: leaderboard readability (score, cost, time, tokens) with a compact header and no decorative logo blocks. Serif display headings paired with sans body and UI.

## Colors

Deep navy background (`#0a1220`) with blue-tinted cards (`#121f35`, `#182a45`). Three blues (`#4a9eed`, `#2d6fc4`, `#7eb8f0`) carry UI chrome, tabs, and chart bars. Warm brown accent (`#c4956a`) for score highlights and one methodology column. Green (`#45c985`) and red (`#e85d6a`) for pass/fail badges and semantic accents. Muted text `#8fa8c8` on card surfaces.

Subtle ambient orbs and grid lines are allowed at low opacity; no glassmorphism panels or gradient text.

## Typography

- **Display:** Newsreader for h1/h2 section titles. Max hero size via clamp; no shouting above ~2.65rem on this product surface.
- **UI + body:** Instrument Sans for nav, controls, tables, captions.
- **Mono:** System monospace for commands and code blocks only.
- No all-caps body copy. Uppercase reserved for short table headers and stat labels.

## Elevation

Flat cards with 1px border (`rgba(255,255,255,0.09)`). No drop shadows as default chrome. Dashed border for empty chart state only. Sticky header with light backdrop blur.

## Components

- **Header:** Text wordmark (name + short tagline), inline nav, GitHub CTA. No icon-in-square logo.
- **Metric tabs:** Segmented control in a bordered pill; active state uses accent-soft fill.
- **Chart card:** Title + caption block above chart body; empty state lives inside chart body, never overlapping caption.
- **Results table:** Full-width, uppercase column headers, row hover/focus highlight in accent tint.
- **Stat grid:** 2x2 compact chips for suite/models/updated/top score in hero.

## Do's and Don'ts

**Do**

- Keep content width around 1240px with tight vertical rhythm (sections ~2rem apart).
- Use commas, colons, or periods instead of em dashes in copy.
- Hide chart canvas when empty; show centered empty message inside chart body.
- Respect `prefers-reduced-motion: reduce`.

**Don't**

- Add MB or initial-based logo marks.
- Stack empty-state text over chart captions.
- Use purple gradients, glass cards, or side-stripe borders.
- Pad sections with full-viewport whitespace.
- Use placeholder em dashes for missing numeric values; use `n/a` instead.
