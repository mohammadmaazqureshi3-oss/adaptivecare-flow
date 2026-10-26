# Part I — Outline planning and architectural design {.unnumbered}

# Introduction

## Problem

A clinical pathway describes what happens to a patient with a given problem: who measures what,
which decisions are taken on which data, what must happen within how many minutes, and what
happens when something fails. Emergency departments revise these pathways often — after an
audit, a new guideline or a staffing change. When the pathway lives inside application code,
every revision is a software project, so the software lags behind the clinical rules, or
the rules are followed on paper beside the software.

Three questions decide whether a revised pathway can be trusted, and today they are usually
answered by inspection and experience:

1. **Is it safe?** Can a patient get stuck, have a step done twice, or reach a step that reads
   a value nobody has measured yet?
2. **Can we staff it?** With the expected arrivals, how long will patients wait, how many
   deadlines will be missed, and how many nurses and doctors are needed?
3. **Will it run correctly?** In a distributed system where messages are duplicated, delayed
   and lost, and servers crash, does every patient case still follow the pathway exactly once?

## Goal

AdaptiveCare Flow lets staff answer these questions with software instead of inspection. A
pathway designer draws the pathway in a web editor. The platform then

- **verifies** it, proving the absence of deadlocks, livelocks, unfinished cases, dead steps,
  duplicate work and missing data, or showing the shortest path to each error;
- **simulates** it under a realistic load, with confidence intervals, and recommends the
  cheapest staffing that meets every deadline target;
- **deploys** a published version as its own engine container with its own queue; and
- **runs** every patient's case through it, across services, through events.

The three decisions the system makes, and the algorithm that makes each, are summarised in
Table 1.1. This is the project's answer to the question "how does your system decide?".

| When | Decision | Algorithm | Result |
|------|----------|-----------|--------|
| Design time | Is this pathway safe to run? | 1. Pathway Verifier | SAFE, or each error with a counterexample path |
| Planning time | How many staff does it need to meet its deadlines? | 3. Pathway Simulator and Staffing Advisor | Waits and deadline misses with 95% intervals, and the cheapest staffing that meets every target |
| Run time | What happens next for this patient? | 2. Execution Engine | The next steps, correct even with duplicate, late or lost messages and crashes |

: Table 1.1 — The three decisions and the algorithms that make them.

All three algorithms use one shared library of token rules, `pathway-core`. What is verified
and simulated is therefore exactly what runs.

## Scope

**In scope:** the pathway editor with live checks, versions, Verify, Simulate, Compare, Publish
and Deploy; the three algorithms; eleven services connected by events; one machine-learning
model (patient urgency) used as a step inside pathways; three clinical pathways built with the
platform (Triage, Assessment and Visit); monitoring, alerts and encrypted patient identifiers;
synthetic or public de-identified data only.

**Out of scope**, stated once so the scope stays fixed: real hospital systems (HL7, FHIR), real
patient data, mobile apps, ambulance dispatch and routing, staff rostering, moving running cases
to a new pathway version (a stretch goal, `MIG-01`), and full BPMN 2.0 compatibility.

## Contributions

1. A **pathway language** with eight token rules, a condition language with its own lexer,
   recursive-descent parser, type checker and evaluator, and per-step policies (deadlines and
   escalation chains, retries with an answer timeout, fallbacks, undo actions, override checks,
   announced events) — chapter 7 and 8.
2. **Algorithm 1**, a verifier that combines state-space search, co-reachability, a data-flow
   fixed point and condition type checking, and returns shortest counterexamples that the editor
   replays step by step — chapter 8.
3. **Algorithm 2**, an event-driven execution engine with deterministic identifiers, per-case
   locking, a transactional outbox, event-sourced recovery with snapshots, persisted timers,
   escalation, retries and compensation in reverse happened-before order — chapters 9 and 10.
4. **Algorithm 3**, a discrete-event simulator with thinning for hourly arrivals, priority
   queues, adaptive replications and Student-t intervals, validated against queueing theory,
   plus a greedy staffing advisor measured against exhaustive search — chapter 11.
5. A **microservice platform** around them: model-driven deployment (each published model
   becomes an engine configuration), monitoring, alerts, an urgency model with explanations,
   and three working clinical pathways — chapters 10, 12 and 13.
6. A documented **AI-assisted process**: a rules file, a prompt log per sprint, and a record of
   where the AI was wrong and how tests caught it — chapter 14.

## Structure of the report

Part I covers outline planning: background and related work (chapter 2), the development process
(chapter 3), requirements (chapter 4) and the architecture (chapter 5). Part II has one chapter
per sprint, Sprint 0 to Sprint 7 (chapters 6–13). Part III covers project closure: AI-assisted
development (chapter 14), testing and quality (chapter 15), and evaluation and lessons learned
(chapter 16). The appendices hold the full backlog with its traceability, the event contract,
and excerpts of the prompt log.
