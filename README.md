# PredictionMarket

Multi-outcome parimutuel prediction market with consensus settlement, on GenLayer Stable Studionet.

- Contract: `0xEedB8c6f3d3aa7b736f226c5E1B7d5D633e077FA`
- Network: Stable Studionet (Chain ID 61999)
- Explorer: https://explorer-studio.genlayer.com/address/0xEedB8c6f3d3aa7b736f226c5E1B7d5D633e077FA
- Evidence: [`evidence/live-verification.json`](evidence/live-verification.json)

## What it is

Anyone can create a market on a subjective event with 3 or more mutually exclusive outcomes. Bettors stake TEST GEN into a common pool; each outcome's share of the pool is its implied odds, and the odds move with every bet. When the event is over, anyone proposes the winning outcome with evidence. GenLayer validators independently judge whether the evidence credibly establishes an outcome under the market's written settlement criteria. Only a consensus verdict settles the money:

- **Winning outcome** — winners split 98% of the pool pro-rata by stake, 2% goes to the platform pool as a fee, losers lose their stake.
- **INVALID** — the evidence is contradictory or names no deciding source, so every bet is refunded in full and no fee is charged.
- **Dispute** — a verdict can be disputed once with counter-evidence before settlement; the re-adjudication is final.

This mirrors the Polymarket pattern (parimutuel pool, pair-minted outcome tokens, UMA-style dispute by bond) with the missing piece added: a consensus court that judges whether the submitted evidence actually establishes the outcome, instead of a centralized team or a token-holder vote.

## Lifecycle

```
claim_test_gen()                 1,000 TEST GEN, once per address (nominal in-contract ledger)
create_market(question, outcomes, criteria, source)
                                 3-8 distinct outcomes, joined with "|"
bet(market_id, outcome, amount)  stake TEST GEN into the pool; odds move with every bet
propose_outcome(market_id, outcome, evidence)
                                 anyone; needs at least one bet in the pool
adjudicate(market_id)            validators judge the evidence; OUTCOME|<index> or INVALID
dispute(market_id, claim, evidence)
                                 once, only after a verdict, only before settlement
adjudicate_dispute(market_id)    re-judges with the counter-evidence; final
settle(market_id)                applies the verdict: pay winners, or refund everyone
```

Explicit triggers only: there is no wall-clock deadline anywhere. Betting ends when someone proposes an outcome; settlement happens when someone calls settle after a verdict. A market with no bets can be cancelled by its creator.

## Consensus

`adjudicate` / `adjudicate_dispute` run the evidence through `gl.nondet.exec_prompt` inside `gl.vm.run_nondet_unsafe`. The leader asks an LLM to return exactly one line, `OUTCOME|<index>` or `INVALID`, from the market's written settlement criteria. Each validator independently re-runs the same prompt on the same stored evidence and the verdicts must be strictly equal as strings. Free-text reasons are not part of the verdict. Any failure (unparsable verdict, disagreement) raises before any write, so the market stays in its pre-verdict state and can be retried. A decided market can never be re-adjudicated except through the one dispute; post-verdict notes are kept as witness entries without changing the standing verdict.

## Money

All amounts are integers in microGEN (1 GEN = 1,000,000 microGEN), stored as strings. No floats anywhere. Balances are a nominal in-contract TEST ledger: `claim_test_gen` credits 1,000 GEN once per address, and bets, payouts, refunds and fees only move ledger entries. No real GEN is transferred by this contract.

| Rule | Value |
| --- | --- |
| Minimum bet | 1 GEN |
| Maximum bet | 10,000 GEN per bet |
| Outcomes per market | 3 – 8 |
| Settlement fee | 2% of the pool |
| Winner split | 98% of the pool, pro-rata by stake on the winning outcome |
| INVALID verdict | full refund of every bet, no fee |
| Odds | outcome_total * 10000 // total_pool (basis points of the pool) |

## Calling it

The contract is a reusable primitive: one contract, no frontend. Call it with `genlayer-py` against Studionet (`https://studio.genlayer.com/api`, chain 61999) or the GenLayer CLI. See [`scripts/verify_studionet.py`](scripts/verify_studionet.py) for a complete end-to-end call sequence (deploy, fund, create, bet, propose, adjudicate, dispute, settle, read-back).

Views: `get_market(market_id)`, `get_bet(bet_id)`, `get_balance(address)`, `get_platform_pool()`, `get_odds(market_id)`, `get_position(market_id, address)`, `get_next_market_id()`.

## Live verification (Studionet)

Deployed and exercised on Stable Studionet. All 27 transactions reached FINALIZED with leader execution `SUCCESS`; state was read back afterwards.

| Market | Verdict | Settlement |
| --- | --- | --- |
| 1 — 2024 US election, 100 GEN pool, odds 6000\|3000\|1000 after bets | `OUTCOME\|0` | `SETTLED_PAID`, winner takes 98 GEN, 2 GEN fee |
| 2 — UMA dispute bond, 60 GEN pool, wrong proposal corrected, then disputed | `OUTCOME\|0`, dispute verdict `OUTCOME\|0` | `SETTLED_PAID`, winner takes 58.8 GEN, 1.2 GEN fee |
| 3 — contradictory evidence, 30 GEN pool | `INVALID` | `SETTLED_REFUNDED`, full refund, no fee |

Final read-back: platform pool 3.2 GEN; creator balance 1,076.8 GEN; bettor B 950 GEN; bettor C 970 GEN. Full transaction hashes, receipts and read-back state are in [`evidence/live-verification.json`](evidence/live-verification.json); the deployment record is in [`evidence/DEPLOYMENT.md`](evidence/DEPLOYMENT.md).

## Tests

Direct-mode tests (mocked LLM, validator exercised explicitly):

```bash
pip install -r requirements.txt
python -m pytest tests/ -q   # 15 passed
```

## Known limitations

See [`evidence/KNOWN_LIMITATIONS.md`](evidence/KNOWN_LIMITATIONS.md).
