---
title: "AdaptiveCare Flow"
subtitle: "A low-code platform to verify, simulate, deploy and run clinical pathways — final project report"
author: "Mohammad Maaz Qureshi"
date: "October 2026"
---

# Abstract {.unnumbered}

Clinical pathways — the agreed sequence of steps for a patient with a given problem, such as
emergency triage — change often, and software that hard-codes them cannot follow. AdaptiveCare
Flow is a low-code platform in which staff draw a pathway in a web editor, and the system
proves that it is safe, predicts how many staff it needs, deploys it as its own microservice
and runs it for every patient.

Three custom algorithms make these decisions. The **Pathway Verifier** (Algorithm 1) explores
every state a case could reach and checks soundness in the sense of van der Aalst's workflow
nets, plus data soundness; every error comes with the shortest path that causes it. The
**Execution Engine** (Algorithm 2) runs real cases across services through events and keeps
five invariants — no event changes a case twice, a join fires once, replay rebuilds the same
state, every case ends in one final state, and no task is lost in a crash. The **Pathway
Simulator and Staffing Advisor** (Algorithm 3) runs virtual patients through the same token
rules, reports waits and missed deadlines with 95% confidence intervals, is validated against
the Erlang C formula, and recommends the cheapest staffing that meets every deadline target.
All three share one library, so what is verified and simulated is exactly what runs.

The platform has eleven services that communicate through a topic exchange. It ships three
clinical pathways built with the platform itself (Triage with an urgency model and the NEWS2
score, Assessment and Visit) and an urgency model trained by a documented pipeline. The
project followed Scrum's three phases with eight tagged increments and was built with an AI
coding assistant under written rules, with every increment's prompts, the AI's mistakes and
how tests caught them recorded.

Measured results: verification in 0.04 s (target 2 s); engine event handling p95 3 ms at
250 events per second (target 200 ms at 50); 30 simulation replications of 7 days in 5.0 s
(target 60 s); model prediction p95 11 ms (target 100 ms); Erlang C inside the simulated
interval in 92 of 100 experiments (target 90); 94.3% statement coverage over 664 automated tests.
Limits are stated where they apply: the model is trained on synthetic data, the Docker and
RabbitMQ paths have not been run on the measuring machine, the alpha usability test is still
to be held, and the increments were built in two days rather than the sixteen weeks planned.

# How to read this report {.unnumbered}

The report follows Scrum's three phases (course slides *5 – Agile development*): **Part I**
(chapters 1–5) is outline planning and architectural design, **Part II** (chapters 6–13) has
one chapter per sprint, and **Part III** (chapters 14–16) is project closure. Every sprint
chapter has the same eight parts: goal, sprint backlog, user stories with acceptance criteria,
design with UML, implementation notes, AI usage, tests and results, and review and
retrospective.

Identifiers are used throughout and are traceable from story to test to diagram (appendix B):
stories such as `ENG-05`, non-functional requirements such as `NFR-PERF-02`, diagrams `U01`–`U32`
and `E1`, design decisions `0001`–`0008`, and the engine's invariants `I1`–`I5`. Paths such as
`services/engine/engine/case.py` refer to the repository; the tag `sprint-N` holds the state
at the end of each sprint.
