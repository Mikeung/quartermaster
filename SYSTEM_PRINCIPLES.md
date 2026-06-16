# System Principles

## Understanding Is the Goal
The product exists to explain unfamiliar VPS environments to a new operator without
asking the original builders. Discovery is an input; reports are an output;
understanding is the goal. Before any work: *"Does this improve understanding of an
unfamiliar VPS?"* (See [`UNDERSTANDING_ERA.md`](UNDERSTANDING_ERA.md).)

## Answer + Confidence + Evidence
Every explanation carries an answer, a confidence level (High/Medium/Low), and the
observable evidence behind it. Unknown is acceptable. Hallucination is not.

## Operational Truth Over AI Creativity
Facts first. Inference second. Inference is labeled as inference, with confidence.

## Read-Only Intelligence
The system advises only.

## Continuous Reconstruction
Infrastructure understanding must continuously refresh.

## Human Authority
Humans make decisions.

## Simplicity First
Avoid unnecessary architectural complexity.

## VPS-First
Optimize for solo-dev operational simplicity.

## Observable Systems
All important behaviors must be logged and traceable.

## Repository History Is Operational Memory
A task does not exist unless it is recorded; a decision does not exist unless it is
recorded. Artifacts, TASK_LOG, and DECISION_LOG are the durable memory.
