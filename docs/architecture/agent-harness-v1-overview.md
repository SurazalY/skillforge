# Agent Harness v1 Overview

Agent Harness v1 describes the skillforge runtime shape: a local command line agent, a bounded workspace tool set, explicit task state, and local run artifacts.

The core loop keeps task state separate from the transcript so checkpoint, resume, evaluator, and metric paths can inspect progress without replaying raw model output.
