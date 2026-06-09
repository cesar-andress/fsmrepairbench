# FSMRepairBench v0.2.0 Benchmark Campaign Report

**Dataset:** `data/fsmrepairbench_v0_2`  
**Generated:** 2026-06-09T01:29:25.597064+00:00  
**Cases:** 1000

## Campaign Overview

This campaign builds a taxonomy-balanced stratified benchmark and runs existing FSMRepairBench analyses: feature-space coverage, behavioural scoring (BPR), spectrum-based fault localization, and mutation coupling.

## Automata Family Coverage

| Family | Cases | Share |
|---|---:|---:|
| DFA | 150 | 15.00% |
| EFSM | 200 | 20.00% |
| Mealy | 200 | 20.00% |
| Moore | 150 | 15.00% |
| NFA | 100 | 10.00% |
| Timed FSM | 200 | 20.00% |

## Behavioural Scoring

- Mean reference BPR: **1.0000**
- Mean faulty BPR: **0.5280**
- Mean BPR delta: **0.4720**
- Fault detection rate: **75.00%**

## Fault Localization

- Method: `ochiai`
- Localized cases: **750**
- Top-1 transition hit rate: **0.00%**
- Top-5 transition hit rate: **37.73%**

## Coupling Analysis

- First-order detection rate: **75.00%**
- Higher-order detection rate: **0.00%**
- Coupling effect estimate: **0.00%**

## Feature-Space Coverage

- Unique taxonomy combinations: **36**
- Missing core combinations: **4779**

## Artifacts

- `summary.json` / `summary.csv` — campaign aggregates
- `distributions.csv` — bucketed taxonomy and BPR distributions
- `mutation_summary.csv` — per-case mutation and detection table (dataset root)
- `coverage_report.json` — feature-space coverage analysis (dataset root)
- `coupling_report.json` — coupling-effect report (campaign directory)

