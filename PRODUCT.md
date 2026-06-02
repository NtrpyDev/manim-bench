# Product

## Register

product

## Users

ManimBench is used by benchmark maintainers and model evaluators who need to generate, render, score, compare, and publish Manim Community Edition benchmark runs. They work in a local developer environment, often with provider API keys, existing output folders, saved runs, and a separate public site repository.

## Product Purpose

ManimBench evaluates how well AI models create high-quality mathematical animations in ManimCE. Success means runs are reproducible, resumable, cost-aware, publishable, and easy to inspect without duplicating benchmark logic across entry points.

## Brand Personality

Precise, technical, trustworthy. The interface should feel like a serious operations tool for expensive benchmark work: calm, dense, and explicit about state, cost, and risk.

## Anti-references

Avoid marketing-site polish, decorative dashboards, wizard-first flows, hidden destructive actions, and playful treatment of provider spend or publish state. The interface should not resemble a generic SaaS landing page, a chat app, or a toy terminal skin.

## Design Principles

- Keep benchmark state visible: model selection, task progress, outputs, spend, and publish readiness should be visible without forcing a linear wizard.
- Reuse the engine as the source of truth: UI actions must call existing orchestration paths instead of reimplementing generation, rendering, reporting, or publishing.
- Make cost and resumability explicit: skip, retry, smoke, cancel, and force behavior should be clear before money or time is spent.
- Treat publishing as a guarded operation: incomplete runs, draft/live target, manifest integrity, and site output must be surfaced before execution.
- Favor dense, predictable controls over decorative presentation.

## Accessibility & Inclusion

Target WCAG 2.1 AA where applicable for terminal UI contrast, focus visibility, keyboard operation, and non-color-only status indicators. Avoid motion that is unrelated to state changes, and ensure all primary actions remain reachable from the keyboard.
