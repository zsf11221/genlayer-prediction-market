# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

"""PredictionMarket: a multi-outcome parimutuel prediction market on GenLayer.

Anyone can create a market on a subjective event with 3 or more mutually
exclusive outcomes. Bettors stake TEST GEN into a common pool; the share
of the pool on each outcome is that outcome's implied odds, and the odds
move with every bet. When the event is over, anyone proposes the winning
outcome with evidence. GenLayer validators independently judge whether
the evidence credibly establishes an outcome under the market's written
settlement criteria. Only a consensus verdict settles the money: the
winners split 98% of the pool pro-rata by stake, 2% goes to the platform
pool as a fee. A verdict can be disputed once with counter-evidence; the
re-adjudication is final. If the evidence is contradictory or names no
deciding source, the verdict is INVALID and every bet is refunded in
full, with no fee.

Category / mechanism / interaction / evolution (four lines):
- Category: markets and wagers.
- Mechanism: consensus decides which outcome of a subjective event won;
  the verdict moves real (nominal TEST) money -- winners split the pool,
  losers lose their stake, an INVALID verdict refunds everyone.
- Interaction model: a market lifecycle (create -> bet -> propose ->
  adjudicate -> dispute -> re-adjudicate -> settle), not a form + list.
- Evolution state: the pool, the implied odds, every bettor's position
  and the settled-market record change with every bet and settlement.

Money design (all integers, no floats anywhere):
- GEN is accounted in microGEN: 1 GEN = 1_000_000 microGEN.
- All amounts are stored as strings of integers and parsed back to int.
- GEN balances are a nominal in-contract TEST ledger.
  claim_test_gen() credits 1_000 GEN once per address; bets, payouts,
  refunds and fees only move ledger entries. No real GEN is transferred
  by this contract.
- Minimum bet: 1 GEN. Maximum bet: 10_000 GEN per bet.
- Settlement fee: 2% of the pool (200 basis points). Winners split the
  remaining 98% pro-rata by their stake on the winning outcome. Integer
  division dust left over after the split also goes to the platform
  pool, so payouts + fee + dust always equal the pool exactly.
- An INVALID verdict refunds every bet in full and charges no fee.

Consensus (adjudicate / adjudicate_dispute):
- The leader asks an LLM to judge the attached evidence against the
  market's written settlement criteria and return exactly one line:
  "OUTCOME|<index>" or "INVALID". Each validator independently re-runs
  the same prompt on the same stored evidence and the verdicts must be
  strictly equal as strings. Free-text reasons are deliberately NOT part
  of the verdict: two independent LLM calls never word a sentence
  identically, so strict equality applies to the canonical verdict.
- The verdict judges evidence sufficiency, not a bare fact: the evidence
  must credibly establish the outcome it names, under the written
  criteria, and name a deciding source. Evidence that contradicts the
  proposed outcome, or that is contradictory or source-free, cannot
  settle a market -- it is either corrected to the outcome the evidence
  does establish, or judged INVALID.
- Any failure (unparsable verdict, consensus disagreement) raises before
  any write, so the market stays in its pre-verdict state and the
  adjudication can be retried.
- A decided market can never be re-adjudicated, except through the one
  dispute. The dispute verdict is final. Notes submitted after a final
  verdict are kept as witness entries while the standing verdict stays
  untouched.

No clock source:
- There is no wall-clock deadline anywhere in this contract. Betting
  ends only when someone proposes an outcome; settlement happens only
  when someone calls settle after a verdict. A market with no bets can
  be cancelled by its creator, refunding any bets placed.
"""

from dataclasses import dataclass

from genlayer import *

# ---------------------------------------------------------------- units
MICRO_PER_GEN = 1_000_000

CLAIM_AMOUNT = 1_000 * MICRO_PER_GEN  # 1000 GEN test credit, once per address
MIN_BET = 1 * MICRO_PER_GEN  # 1 GEN minimum bet
MAX_BET = 10_000 * MICRO_PER_GEN  # 10_000 GEN maximum single bet
FEE_BP = 200  # 2% of the pool goes to the platform pool on settlement

MIN_OUTCOMES = 3
MAX_OUTCOMES = 8

MAX_TEXT_LEN = 3000
MAX_QUESTION_LEN = 300
MAX_OUTCOME_LEN = 100

STATUS_OPEN = "OPEN"
STATUS_PROPOSED = "PROPOSED"
STATUS_ADJUDICATED = "ADJUDICATED"
STATUS_DISPUTED = "DISPUTED"
STATUS_SETTLED_PAID = "SETTLED_PAID"
STATUS_SETTLED_REFUNDED = "SETTLED_REFUNDED"
STATUS_CANCELLED = "CANCELLED"


@allow_storage
@dataclass
class Market:
    id: str
    question: str
    outcomes: str  # outcomes joined with "|"
    criteria: str
    evidence_source: str
    creator: str
    status: str
    proposed_outcome: str
    proposal_evidence: str
    verdict: str
    dispute_claim: str
    dispute_evidence: str
    dispute_count: str
    total_pool: str
    history: str


@allow_storage
@dataclass
class Bet:
    id: str
    market_id: str
    bettor: str
    outcome: str
    amount: str


def _parse_int(value: str, what: str) -> int:
    try:
        return int(value)
    except (ValueError, TypeError):
        raise gl.vm.UserError("[EXPECTED] " + what + " must be a string integer, got: " + str(value))


def _split_outcomes(outcomes: str) -> list:
    parts = [p.strip() for p in outcomes.split("|")]
    if len(parts) < MIN_OUTCOMES or len(parts) > MAX_OUTCOMES:
        raise gl.vm.UserError(
            "[EXPECTED] A market needs between 3 and 8 outcomes, got: " + str(len(parts))
        )
    for part in parts:
        if part == "" or len(part) > MAX_OUTCOME_LEN:
            raise gl.vm.UserError("[EXPECTED] Each outcome must be non-empty and at most 100 characters")
    if len(set(parts)) != len(parts):
        raise gl.vm.UserError("[EXPECTED] Outcomes must be distinct")
    return parts


def _parse_verdict(raw: str, n_outcomes: int) -> str:
    """Normalize raw LLM output to the strict verdict string.

    Only "OUTCOME|<index>" with an in-range index, or "INVALID", is
    accepted. Anything else is an LLM error: raise before writing.
    """
    if not isinstance(raw, str):
        raise gl.vm.UserError("[LLM_ERROR] Verdict is not a string")
    line = raw.strip().split("\n")[0].strip()
    if line.upper() == "INVALID":
        return "INVALID"
    parts = line.split("|")
    if len(parts) != 2:
        raise gl.vm.UserError("[LLM_ERROR] Verdict must be OUTCOME|<index> or INVALID, got: " + line[:120])
    decision = parts[0].strip().upper()
    index_text = parts[1].strip()
    if decision != "OUTCOME":
        raise gl.vm.UserError("[LLM_ERROR] Unknown verdict: " + line[:120])
    try:
        index = int(index_text)
    except ValueError:
        raise gl.vm.UserError("[LLM_ERROR] Outcome index is not an integer: " + line[:120])
    if index < 0 or index >= n_outcomes:
        raise gl.vm.UserError("[LLM_ERROR] Outcome index out of range: " + line[:120])
    return "OUTCOME|" + str(index)


def _settlement_prompt(
    question: str,
    outcomes: list,
    criteria: str,
    evidence_source: str,
    proposed_outcome: str,
    proposal_evidence: str,
    dispute_claim: str,
    dispute_evidence: str,
) -> str:
    numbered = "\n".join(str(i) + ". " + o for i, o in enumerate(outcomes))
    prompt = (
        "You judge a prediction market settlement. "
        "Judge ONLY the question, outcomes, settlement criteria and evidence below; "
        "do not use outside knowledge.\n"
        "Question: " + question + "\n"
        "Outcomes:\n" + numbered + "\n"
        "Settlement criteria:\n" + criteria + "\n"
        "Evidence source named by the market: " + evidence_source + "\n"
        "Proposed winning outcome: " + proposed_outcome + "\n"
        "Evidence attached to the proposal:\n" + proposal_evidence + "\n"
    )
    if dispute_evidence.strip() != "":
        prompt = prompt + (
            "Counter-evidence submitted in dispute (it claims the winning outcome is "
            + dispute_claim + "):\n" + dispute_evidence + "\n"
        )
    prompt = prompt + (
        "Rules:\n"
        "1. Reply OUTCOME|<index> for the outcome the evidence credibly establishes "
        "under the settlement criteria. The evidence must name the winner, the event, "
        "and a deciding source.\n"
        "2. If the attached evidence actually establishes a different listed outcome "
        "than the one proposed, reply with that outcome's index, not the proposed one.\n"
        "3. Reply INVALID if the evidence is contradictory, names no deciding source, "
        "or does not establish any listed outcome.\n"
        "Reply with EXACTLY ONE LINE and nothing else, no markdown, no extra words:\n"
        "OUTCOME|0 or OUTCOME|1 or ... or INVALID"
    )
    return prompt


class PredictionMarket(gl.Contract):
    markets: TreeMap[str, Market]
    bets: TreeMap[str, Bet]
    next_market_id: str
    next_bet_id: str
    gen_balances: TreeMap[Address, str]
    claimed: TreeMap[Address, str]
    platform_pool: str

    def __init__(self):
        self.next_market_id = "1"
        self.next_bet_id = "1"
        self.platform_pool = "0"

    # ------------------------------------------------------------ helpers
    def _get_market(self, market_id: str) -> Market:
        if market_id not in self.markets:
            raise gl.vm.UserError("[EXPECTED] Unknown market: " + market_id)
        return self.markets[market_id]

    def _save_market(self, market: Market) -> None:
        self.markets[market.id] = market

    def _gen_balance_of(self, address: Address) -> int:
        return _parse_int(self.gen_balances.get(address, "0"), "GEN balance")

    def _set_gen_balance(self, address: Address, amount: int) -> None:
        if amount < 0:
            raise gl.vm.UserError("[EXPECTED] GEN balance cannot be negative")
        self.gen_balances[address] = str(amount)

    def _outcome_totals(self, market_id: str, n_outcomes: int) -> list:
        totals = [0] * n_outcomes
        for _bet_id, bet in self.bets.items():
            if bet.market_id == market_id:
                totals[_parse_int(bet.outcome, "bet outcome")] += _parse_int(bet.amount, "bet amount")
        return totals

    def _market_bets(self, market_id: str) -> list:
        return [bet for _bet_id, bet in self.bets.items() if bet.market_id == market_id]

    def _run_consensus(self, prompt: str, n_outcomes: int) -> str:
        def leader_fn():
            raw = gl.nondet.exec_prompt(prompt)
            return _parse_verdict(raw, n_outcomes)

        def validator_fn(leaders_res):
            if not isinstance(leaders_res, gl.vm.Return):
                # Leader errored: agree only if we fail the same way.
                try:
                    leader_fn()
                except gl.vm.UserError as e:
                    leader_msg = leaders_res.message if hasattr(leaders_res, "message") else ""
                    mine_msg = e.message if hasattr(e, "message") else str(e)
                    return mine_msg == leader_msg
                except Exception:
                    return False
                return False
            mine = leader_fn()
            return mine == leaders_res.calldata

        return gl.vm.run_nondet_unsafe(leader_fn, validator_fn)

    def _market_dict(self, market: Market) -> dict:
        outcomes = _split_outcomes(market.outcomes)
        totals = self._outcome_totals(market.id, len(outcomes))
        return {
            "id": market.id,
            "question": market.question,
            "outcomes": market.outcomes,
            "criteria": market.criteria,
            "evidence_source": market.evidence_source,
            "creator": market.creator,
            "status": market.status,
            "proposed_outcome": market.proposed_outcome,
            "proposal_evidence": market.proposal_evidence,
            "verdict": market.verdict,
            "dispute_claim": market.dispute_claim,
            "dispute_evidence": market.dispute_evidence,
            "dispute_count": market.dispute_count,
            "total_pool": market.total_pool,
            "outcome_totals": "|".join(str(t) for t in totals),
            "history": market.history,
        }

    def _bet_dict(self, bet: Bet) -> dict:
        return {
            "id": bet.id,
            "market_id": bet.market_id,
            "bettor": bet.bettor,
            "outcome": bet.outcome,
            "amount": bet.amount,
        }

    # ------------------------------------------------------------ test GEN
    @gl.public.write
    def claim_test_gen(self) -> str:
        sender = gl.message.sender_address
        if self.claimed.get(sender, "0") == "1":
            raise gl.vm.UserError("[EXPECTED] Test GEN already claimed by this address")
        self.claimed[sender] = "1"
        self._set_gen_balance(sender, self._gen_balance_of(sender) + CLAIM_AMOUNT)
        return str(CLAIM_AMOUNT)

    # ------------------------------------------------------------ markets
    @gl.public.write
    def create_market(self, question: str, outcomes: str, criteria: str, evidence_source: str) -> str:
        if question.strip() == "" or len(question) > MAX_QUESTION_LEN:
            raise gl.vm.UserError("[EXPECTED] Question must be non-empty and at most 300 characters")
        _split_outcomes(outcomes)  # validates count, length, distinctness
        if criteria.strip() == "" or len(criteria) > MAX_TEXT_LEN:
            raise gl.vm.UserError("[EXPECTED] Settlement criteria must be non-empty and at most 3000 characters")
        if evidence_source.strip() == "" or len(evidence_source) > MAX_TEXT_LEN:
            raise gl.vm.UserError("[EXPECTED] Evidence source must be non-empty and at most 3000 characters")
        sender = gl.message.sender_address
        market_id = self.next_market_id
        self.next_market_id = str(int(market_id) + 1)
        market = Market(
            id=market_id,
            question=question,
            outcomes=outcomes,
            criteria=criteria,
            evidence_source=evidence_source,
            creator=sender.as_hex,
            status=STATUS_OPEN,
            proposed_outcome="",
            proposal_evidence="",
            verdict="",
            dispute_claim="",
            dispute_evidence="",
            dispute_count="0",
            total_pool="0",
            history="CREATED",
        )
        self.markets[market_id] = market
        return market_id

    @gl.public.write
    def cancel_market(self, market_id: str) -> str:
        market = self._get_market(market_id)
        sender = gl.message.sender_address
        if market.creator != sender.as_hex:
            raise gl.vm.UserError("[EXPECTED] Only the market creator can cancel this market")
        if market.status != STATUS_OPEN:
            raise gl.vm.UserError("[EXPECTED] Only an OPEN market can be cancelled: " + market.status)
        for bet in self._market_bets(market_id):
            bettor = Address(bet.bettor)
            self._set_gen_balance(bettor, self._gen_balance_of(bettor) + _parse_int(bet.amount, "bet amount"))
        market.total_pool = "0"
        market.status = STATUS_CANCELLED
        market.history = market.history + "\nCANCELLED"
        self._save_market(market)
        return market.status

    # ------------------------------------------------------------ betting
    @gl.public.write
    def bet(self, market_id: str, outcome: str, amount: str) -> str:
        market = self._get_market(market_id)
        if market.status != STATUS_OPEN:
            raise gl.vm.UserError("[EXPECTED] Betting is closed for this market: " + market.status)
        outcomes = _split_outcomes(market.outcomes)
        outcome_index = _parse_int(outcome, "outcome")
        if outcome_index < 0 or outcome_index >= len(outcomes):
            raise gl.vm.UserError("[EXPECTED] Outcome index out of range")
        amount_int = _parse_int(amount, "bet amount")
        if amount_int < MIN_BET or amount_int > MAX_BET:
            raise gl.vm.UserError("[EXPECTED] Bet must be between 1 and 10000 GEN")
        sender = gl.message.sender_address
        if self._gen_balance_of(sender) < amount_int:
            raise gl.vm.UserError("[EXPECTED] Insufficient GEN balance for bet")
        self._set_gen_balance(sender, self._gen_balance_of(sender) - amount_int)
        bet_id = self.next_bet_id
        self.next_bet_id = str(int(bet_id) + 1)
        self.bets[bet_id] = Bet(
            id=bet_id,
            market_id=market_id,
            bettor=sender.as_hex,
            outcome=str(outcome_index),
            amount=str(amount_int),
        )
        market.total_pool = str(_parse_int(market.total_pool, "total pool") + amount_int)
        market.history = market.history + "\nBET|" + bet_id + "|" + str(outcome_index) + "|" + str(amount_int)
        self._save_market(market)
        return bet_id

    # ------------------------------------------------------------ settlement
    @gl.public.write
    def propose_outcome(self, market_id: str, outcome: str, evidence: str) -> str:
        market = self._get_market(market_id)
        if market.status != STATUS_OPEN:
            raise gl.vm.UserError("[EXPECTED] Only an OPEN market can be proposed: " + market.status)
        outcomes = _split_outcomes(market.outcomes)
        outcome_index = _parse_int(outcome, "outcome")
        if outcome_index < 0 or outcome_index >= len(outcomes):
            raise gl.vm.UserError("[EXPECTED] Outcome index out of range")
        if evidence.strip() == "" or len(evidence) > MAX_TEXT_LEN:
            raise gl.vm.UserError("[EXPECTED] Proposal evidence must be non-empty and at most 3000 characters")
        if _parse_int(market.total_pool, "total pool") <= 0:
            raise gl.vm.UserError("[EXPECTED] Cannot propose an outcome for a market with no bets")
        market.proposed_outcome = str(outcome_index)
        market.proposal_evidence = evidence
        market.status = STATUS_PROPOSED
        market.history = market.history + "\nPROPOSED|" + str(outcome_index)
        self._save_market(market)
        return market.status

    @gl.public.write
    def adjudicate(self, market_id: str) -> str:
        market = self._get_market(market_id)
        if market.status != STATUS_PROPOSED:
            raise gl.vm.UserError("[EXPECTED] Only a PROPOSED market can be adjudicated: " + market.status)
        outcomes = _split_outcomes(market.outcomes)
        prompt = _settlement_prompt(
            market.question,
            outcomes,
            market.criteria,
            market.evidence_source,
            market.proposed_outcome,
            market.proposal_evidence,
            "",
            "",
        )
        verdict = self._run_consensus(prompt, len(outcomes))
        # Consensus reached. Only now, after agreement, write the outcome.
        market.verdict = verdict
        market.history = market.history + "\nADJUDICATED|" + verdict
        market.status = STATUS_ADJUDICATED
        self._save_market(market)
        return verdict

    @gl.public.write
    def dispute(self, market_id: str, claimed_outcome: str, evidence: str) -> str:
        market = self._get_market(market_id)
        if market.status != STATUS_ADJUDICATED:
            raise gl.vm.UserError("[EXPECTED] Only an adjudicated market can be disputed: " + market.status)
        if _parse_int(market.dispute_count, "dispute count") >= 1:
            raise gl.vm.UserError("[EXPECTED] This market has already been disputed once")
        outcomes = _split_outcomes(market.outcomes)
        if claimed_outcome.strip().upper() == "INVALID":
            claim = "INVALID"
        else:
            claim_index = _parse_int(claimed_outcome, "claimed outcome")
            if claim_index < 0 or claim_index >= len(outcomes):
                raise gl.vm.UserError("[EXPECTED] Claimed outcome index out of range")
            claim = str(claim_index)
        if evidence.strip() == "" or len(evidence) > MAX_TEXT_LEN:
            raise gl.vm.UserError("[EXPECTED] Dispute evidence must be non-empty and at most 3000 characters")
        market.dispute_claim = claim
        market.dispute_evidence = evidence
        market.dispute_count = "1"
        market.status = STATUS_DISPUTED
        market.history = market.history + "\nDISPUTED|" + claim
        self._save_market(market)
        return market.status

    @gl.public.write
    def adjudicate_dispute(self, market_id: str) -> str:
        market = self._get_market(market_id)
        if market.status != STATUS_DISPUTED:
            raise gl.vm.UserError("[EXPECTED] Only a DISPUTED market can be re-adjudicated: " + market.status)
        outcomes = _split_outcomes(market.outcomes)
        prompt = _settlement_prompt(
            market.question,
            outcomes,
            market.criteria,
            market.evidence_source,
            market.proposed_outcome,
            market.proposal_evidence,
            market.dispute_claim,
            market.dispute_evidence,
        )
        verdict = self._run_consensus(prompt, len(outcomes))
        # Consensus reached. The dispute verdict is final: no second dispute.
        market.verdict = verdict
        market.history = market.history + "\nDISPUTE_ADJUDICATED|" + verdict
        market.status = STATUS_ADJUDICATED
        self._save_market(market)
        return verdict

    @gl.public.write
    def submit_witness(self, market_id: str, note: str) -> str:
        """Attach a note after a verdict. The standing verdict is never
        changed; the note is kept as a witness entry only."""
        if note.strip() == "" or len(note) > MAX_TEXT_LEN:
            raise gl.vm.UserError("[EXPECTED] Witness note must be non-empty and at most 3000 characters")
        market = self._get_market(market_id)
        if market.status not in (
            STATUS_ADJUDICATED,
            STATUS_DISPUTED,
            STATUS_SETTLED_PAID,
            STATUS_SETTLED_REFUNDED,
        ):
            raise gl.vm.UserError("[EXPECTED] Witness notes are only kept after a verdict: " + market.status)
        market.history = market.history + "\nWITNESS|" + note
        self._save_market(market)
        return market.status

    @gl.public.write
    def settle(self, market_id: str) -> str:
        market = self._get_market(market_id)
        if market.status != STATUS_ADJUDICATED:
            raise gl.vm.UserError("[EXPECTED] Only an adjudicated market can be settled: " + market.status)
        pool = _parse_int(market.total_pool, "total pool")
        bets = self._market_bets(market_id)
        if market.verdict == "INVALID":
            for bet in bets:
                bettor = Address(bet.bettor)
                self._set_gen_balance(bettor, self._gen_balance_of(bettor) + _parse_int(bet.amount, "bet amount"))
            market.total_pool = "0"
            market.status = STATUS_SETTLED_REFUNDED
            market.history = market.history + "\nSETTLED|SETTLED_REFUNDED"
            self._save_market(market)
            return market.status
        # Normal settlement: winners split 98% of the pool pro-rata.
        decision, index_text = market.verdict.split("|")
        if decision != "OUTCOME":
            raise gl.vm.UserError("[EXPECTED] Cannot settle a market with verdict: " + market.verdict)
        winning_index = _parse_int(index_text, "winning outcome")
        fee = pool * FEE_BP // 10000
        distributable = pool - fee
        winning_total = sum(
            _parse_int(bet.amount, "bet amount")
            for bet in bets
            if _parse_int(bet.outcome, "bet outcome") == winning_index
        )
        if winning_total <= 0:
            raise gl.vm.UserError("[EXPECTED] No bets on the winning outcome; cannot settle")
        paid_sum = 0
        for bet in bets:
            if _parse_int(bet.outcome, "bet outcome") == winning_index:
                payout = _parse_int(bet.amount, "bet amount") * distributable // winning_total
                if payout > 0:
                    bettor = Address(bet.bettor)
                    self._set_gen_balance(bettor, self._gen_balance_of(bettor) + payout)
                paid_sum += payout
        # Integer division dust plus the fee go to the platform pool, so
        # payouts + fee + dust always equal the pool exactly.
        dust = distributable - paid_sum
        self.platform_pool = str(_parse_int(self.platform_pool, "platform pool") + fee + dust)
        market.total_pool = "0"
        market.status = STATUS_SETTLED_PAID
        market.history = market.history + "\nSETTLED|SETTLED_PAID"
        self._save_market(market)
        return market.status

    # ------------------------------------------------------------ views
    @gl.public.view
    def get_market(self, market_id: str) -> dict:
        return self._market_dict(self._get_market(market_id))

    @gl.public.view
    def get_bet(self, bet_id: str) -> dict:
        if bet_id not in self.bets:
            raise gl.vm.UserError("[EXPECTED] Unknown bet: " + bet_id)
        return self._bet_dict(self.bets[bet_id])

    @gl.public.view
    def get_balance(self, account_address: str) -> str:
        return str(self._gen_balance_of(Address(account_address)))

    @gl.public.view
    def get_platform_pool(self) -> str:
        return self.platform_pool

    @gl.public.view
    def get_next_market_id(self) -> str:
        return self.next_market_id

    @gl.public.view
    def get_odds(self, market_id: str) -> str:
        """Implied odds per outcome in basis points of the pool.

        Returns outcomes joined with "|", e.g. "6000|3000|1000".
        Each value is outcome_total * 10000 // total_pool, or 0 when the
        pool is empty. All integers, no floats.
        """
        market = self._get_market(market_id)
        outcomes = _split_outcomes(market.outcomes)
        totals = self._outcome_totals(market_id, len(outcomes))
        pool = _parse_int(market.total_pool, "total pool")
        if pool <= 0:
            return "|".join("0" for _ in outcomes)
        return "|".join(str(t * 10000 // pool) for t in totals)

    @gl.public.view
    def get_position(self, market_id: str, account_address: str) -> str:
        """One bettor's stake per outcome, joined with "|" (microGEN)."""
        market = self._get_market(market_id)
        outcomes = _split_outcomes(market.outcomes)
        position = [0] * len(outcomes)
        for bet in self._market_bets(market_id):
            if bet.bettor.lower() == account_address.lower():
                position[_parse_int(bet.outcome, "bet outcome")] += _parse_int(bet.amount, "bet amount")
        return "|".join(str(p) for p in position)
