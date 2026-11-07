"""Direct-mode tests for contracts/prediction_market.py (no simulator, no network).

LLM calls are mocked with direct_vm.mock_llm; the consensus validator is
exercised explicitly with direct_vm.run_validator().

Money is microGEN (1 GEN = 1_000_000 microGEN), stored as strings.
Odds are integer basis points of the pool (outcome_total * 10000 // pool).
"""

import pytest

CONTRACT = "contracts/prediction_market.py"

GEN = 1_000_000
CLAIM = 1_000 * GEN

QUESTION = "Which candidate won the 2024 US presidential election?"
OUTCOMES = "Donald Trump|Kamala Harris|Other candidate"
CRITERIA = (
    "The market settles on the candidate named as the winner in the attached "
    "evidence. The evidence must name the winner, the election year, and a "
    "deciding source."
)
SOURCE = "Polymarket 2024 US presidential election contract settlement"
GOOD_EVIDENCE = (
    "The 2024 US presidential election was won by Donald Trump. Polymarket's "
    "largest binary contract, with over 3.3 billion dollars of notional volume, "
    "settled on Donald Trump as the winner, confirmed by the official election outcome."
)
THIN_EVIDENCE = "trust me, it was the other one"


def _hex(addr):
    return addr.as_hex if hasattr(addr, "as_hex") else "0x" + bytes(addr).hex()


@pytest.fixture
def work(direct_deploy):
    return direct_deploy(CONTRACT)


def _claim(direct_vm, contract, who):
    direct_vm.sender = who
    return contract.claim_test_gen()


def _create(direct_vm, contract):
    owner = direct_vm.sender
    _claim(direct_vm, contract, owner)
    return contract.create_market(QUESTION, OUTCOMES, CRITERIA, SOURCE)


def _bet(direct_vm, contract, who, market_id, outcome, amount_gen):
    direct_vm.sender = who
    return contract.bet(market_id, str(outcome), str(amount_gen * GEN))


def _setup_market(direct_vm, contract, alice, bob, bets=((0, 60), (1, 30), (2, 10))):
    """Owner + alice + bob claim; market created; bets placed per `bets`.

    `bets` entries are (outcome, amount_gen) in order owner, alice, bob.
    Returns (market_id, [owner, alice, bob]).
    """
    owner = direct_vm.sender
    market_id = _create(direct_vm, contract)
    _claim(direct_vm, contract, alice)
    _claim(direct_vm, contract, bob)
    who = [owner, alice, bob]
    for i, (outcome, amount) in enumerate(bets):
        _bet(direct_vm, contract, who[i], market_id, outcome, amount)
    direct_vm.sender = owner
    return market_id, who


def _mock_verdict(direct_vm, verdict):
    direct_vm.mock_llm("judge a prediction market", verdict)


# ------------------------------------------------------------ setup
def test_claim_and_create_market(direct_vm, work):
    owner = direct_vm.sender
    assert _claim(direct_vm, work, owner) == str(CLAIM)
    assert work.get_balance(_hex(owner)) == str(CLAIM)
    with direct_vm.expect_revert("already claimed"):
        _claim(direct_vm, work, owner)

    market_id = work.create_market(QUESTION, OUTCOMES, CRITERIA, SOURCE)
    assert market_id == "1"
    market = work.get_market("1")
    assert market["status"] == "OPEN"
    assert market["total_pool"] == "0"
    assert market["outcomes"] == OUTCOMES
    assert work.get_next_market_id() == "2"
    assert work.get_odds("1") == "0|0|0"


def test_create_market_rejects_bad_outcomes(direct_vm, work):
    _claim(direct_vm, work, direct_vm.sender)
    with direct_vm.expect_revert("between 3 and 8 outcomes"):
        work.create_market(QUESTION, "Yes|No", CRITERIA, SOURCE)
    with direct_vm.expect_revert("Outcomes must be distinct"):
        work.create_market(QUESTION, "A|A|B", CRITERIA, SOURCE)
    with direct_vm.expect_revert("non-empty"):
        work.create_market("", OUTCOMES, CRITERIA, SOURCE)


def test_bet_moves_odds(direct_vm, work, direct_alice, direct_bob):
    market_id, who = _setup_market(direct_vm, work, direct_alice, direct_bob)
    owner, alice, bob = who
    market = work.get_market(market_id)
    assert market["total_pool"] == str(100 * GEN)
    assert market["outcome_totals"] == "|".join([str(60 * GEN), str(30 * GEN), str(10 * GEN)])
    # Implied odds move with the pool: 6000|3000|1000 basis points.
    assert work.get_odds(market_id) == "6000|3000|1000"
    assert work.get_position(market_id, _hex(owner)) == "|".join([str(60 * GEN), "0", "0"])
    assert work.get_position(market_id, _hex(alice)) == "|".join(["0", str(30 * GEN), "0"])
    assert work.get_balance(_hex(owner)) == str(CLAIM - 60 * GEN)
    assert work.get_balance(_hex(alice)) == str(CLAIM - 30 * GEN)
    assert work.get_balance(_hex(bob)) == str(CLAIM - 10 * GEN)


def test_bet_guards(direct_vm, work, direct_alice):
    owner = direct_vm.sender
    market_id = _create(direct_vm, work)
    _claim(direct_vm, work, direct_alice)
    with direct_vm.expect_revert("Outcome index out of range"):
        _bet(direct_vm, work, direct_alice, market_id, 3, 10)
    with direct_vm.expect_revert("between 1 and 10000 GEN"):
        _bet(direct_vm, work, direct_alice, market_id, 0, 0)
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("Unknown market"):
        work.bet("99", "0", str(10 * GEN))
    # Betting on a market with no proposal yet is fine; proposing needs a pool.
    direct_vm.sender = owner
    with direct_vm.expect_revert("no bets"):
        work.propose_outcome(market_id, "0", GOOD_EVIDENCE)


def test_propose_requires_pool_and_closes_betting(direct_vm, work, direct_alice, direct_bob):
    market_id, who = _setup_market(direct_vm, work, direct_alice, direct_bob)
    owner, alice, bob = who
    direct_vm.sender = owner
    assert work.propose_outcome(market_id, "0", GOOD_EVIDENCE) == "PROPOSED"
    market = work.get_market(market_id)
    assert market["status"] == "PROPOSED"
    assert market["proposed_outcome"] == "0"
    direct_vm.sender = alice
    with direct_vm.expect_revert("Betting is closed"):
        work.bet(market_id, "1", str(5 * GEN))
    with direct_vm.expect_revert("Only an OPEN market"):
        work.propose_outcome(market_id, "1", GOOD_EVIDENCE)


# ------------------------------------------------------------ happy path
def test_happy_path_settle_winners_split_pool(direct_vm, work, direct_alice, direct_bob):
    market_id, who = _setup_market(direct_vm, work, direct_alice, direct_bob)
    owner, alice, bob = who
    direct_vm.sender = owner
    work.propose_outcome(market_id, "0", GOOD_EVIDENCE)
    _mock_verdict(direct_vm, "OUTCOME|0")
    verdict = work.adjudicate(market_id)
    assert verdict == "OUTCOME|0"
    assert direct_vm.run_validator() is True
    market = work.get_market(market_id)
    assert market["status"] == "ADJUDICATED"
    assert market["verdict"] == "OUTCOME|0"

    assert work.settle(market_id) == "SETTLED_PAID"
    market = work.get_market(market_id)
    assert market["status"] == "SETTLED_PAID"
    # Pool 100 GEN: fee 2 GEN, distributable 98 GEN, winner total 60 GEN,
    # owner is the only winner: 60 * 98 // 60 = 98 GEN.
    assert work.get_balance(_hex(owner)) == str(CLAIM - 60 * GEN + 98 * GEN)
    assert work.get_balance(_hex(alice)) == str(CLAIM - 30 * GEN)
    assert work.get_balance(_hex(bob)) == str(CLAIM - 10 * GEN)
    assert work.get_platform_pool() == str(2 * GEN)
    # Books reconcile exactly: 98 paid + 2 fee = 100 pool.
    assert work.get_market(market_id)["total_pool"] == "0"
    # Settling twice is refused.
    with direct_vm.expect_revert("Only an adjudicated market"):
        work.settle(market_id)


def test_fee_split_dust_goes_to_pool(direct_vm, work, direct_alice, direct_bob):
    # Pool 3 GEN split 2/1 across two winners on the same outcome:
    # fee = 3_000_000 * 200 // 10000 = 60_000; distributable 2_940_000.
    # Payouts: 2_000_000 * 2_940_000 // 3_000_000 = 1_960_000;
    #          1_000_000 * 2_940_000 // 3_000_000 = 980_000; dust 0.
    # Then a 7 GEN pool with winners 3/2: fee 140_000, distributable 6_860_000.
    # Payouts: 3_000_000 * 6_860_000 // 5_000_000 = 4_116_000;
    #          2_000_000 * 6_860_000 // 5_000_000 = 2_744_000; dust 0.
    # Dust case: pool 101 microGEN is below the 1 GEN minimum bet, so use
    # a 3-winner split on a 10 GEN pool with fee 200_000, distributable
    # 9_800_000, winner stakes 1/2/3 GEN (total 6 GEN):
    # payouts 1_633_333, 3_266_666, 4_900_000 = 9_799_999, dust 1.
    owner = direct_vm.sender
    market_id = _create(direct_vm, work)
    _claim(direct_vm, work, direct_alice)
    _claim(direct_vm, work, direct_bob)
    _bet(direct_vm, work, owner, market_id, 0, 1)
    _bet(direct_vm, work, direct_alice, market_id, 0, 2)
    _bet(direct_vm, work, direct_bob, market_id, 0, 3)
    _bet(direct_vm, work, owner, market_id, 1, 4)
    direct_vm.sender = owner
    assert work.get_market(market_id)["total_pool"] == str(10 * GEN)
    work.propose_outcome(market_id, "0", GOOD_EVIDENCE)
    _mock_verdict(direct_vm, "OUTCOME|0")
    work.adjudicate(market_id)
    work.settle(market_id)
    # Fee 200_000 + dust 1 = 200_001 in the pool.
    assert work.get_platform_pool() == "200001"
    assert work.get_balance(_hex(owner)) == str(CLAIM - 5 * GEN + 1_633_333)
    assert work.get_balance(_hex(direct_alice)) == str(CLAIM - 2 * GEN + 3_266_666)
    assert work.get_balance(_hex(direct_bob)) == str(CLAIM - 3 * GEN + 4_900_000)


# ------------------------------------------------------------ dispute path
def test_dispute_corrects_wrong_proposal_and_settles(direct_vm, work, direct_alice, direct_bob):
    market_id, who = _setup_market(direct_vm, work, direct_alice, direct_bob)
    owner, alice, bob = who
    direct_vm.sender = owner
    # Propose outcome 1, but the attached evidence establishes outcome 0.
    work.propose_outcome(market_id, "1", GOOD_EVIDENCE)
    _mock_verdict(direct_vm, "OUTCOME|0")
    assert work.adjudicate(market_id) == "OUTCOME|0"
    assert direct_vm.run_validator() is True
    # Dispute claims outcome 2 with thin evidence; re-adjudication keeps 0.
    assert work.dispute(market_id, "2", THIN_EVIDENCE) == "DISPUTED"
    direct_vm.clear_mocks()
    _mock_verdict(direct_vm, "OUTCOME|0")
    assert work.adjudicate_dispute(market_id) == "OUTCOME|0"
    assert direct_vm.run_validator() is True
    market = work.get_market(market_id)
    assert market["status"] == "ADJUDICATED"
    assert market["dispute_count"] == "1"
    assert "DISPUTE_ADJUDICATED|OUTCOME|0" in market["history"]
    # Settle on the final verdict: outcome 0 wins, owner takes 98 GEN.
    assert work.settle(market_id) == "SETTLED_PAID"
    assert work.get_balance(_hex(owner)) == str(CLAIM - 60 * GEN + 98 * GEN)
    assert work.get_platform_pool() == str(2 * GEN)


def test_dispute_only_once_and_only_after_verdict(direct_vm, work, direct_alice, direct_bob):
    market_id, who = _setup_market(direct_vm, work, direct_alice, direct_bob)
    owner = who[0]
    direct_vm.sender = owner
    with direct_vm.expect_revert("Only an adjudicated market"):
        work.dispute(market_id, "1", THIN_EVIDENCE)
    work.propose_outcome(market_id, "0", GOOD_EVIDENCE)
    _mock_verdict(direct_vm, "OUTCOME|0")
    work.adjudicate(market_id)
    work.dispute(market_id, "1", THIN_EVIDENCE)
    direct_vm.clear_mocks()
    _mock_verdict(direct_vm, "OUTCOME|0")
    work.adjudicate_dispute(market_id)
    # The dispute verdict is final: no second dispute.
    with direct_vm.expect_revert("already been disputed"):
        work.dispute(market_id, "1", THIN_EVIDENCE)
    # Settle still works after the dispute.
    assert work.settle(market_id) == "SETTLED_PAID"


# ------------------------------------------------------------ INVALID path
def test_invalid_verdict_refunds_everyone(direct_vm, work, direct_alice, direct_bob):
    market_id, who = _setup_market(direct_vm, work, direct_alice, direct_bob)
    owner, alice, bob = who
    direct_vm.sender = owner
    work.propose_outcome(market_id, "0", GOOD_EVIDENCE)
    _mock_verdict(direct_vm, "INVALID")
    assert work.adjudicate(market_id) == "INVALID"
    assert direct_vm.run_validator() is True
    assert work.settle(market_id) == "SETTLED_REFUNDED"
    # Everyone is refunded in full; no fee is charged.
    assert work.get_balance(_hex(owner)) == str(CLAIM)
    assert work.get_balance(_hex(alice)) == str(CLAIM)
    assert work.get_balance(_hex(bob)) == str(CLAIM)
    assert work.get_platform_pool() == "0"
    assert work.get_market(market_id)["status"] == "SETTLED_REFUNDED"


# ------------------------------------------------------------ cancel / guards
def test_cancel_refunds_open_market(direct_vm, work, direct_alice, direct_bob):
    market_id, who = _setup_market(direct_vm, work, direct_alice, direct_bob)
    owner, alice, bob = who
    direct_vm.sender = alice
    with direct_vm.expect_revert("Only the market creator"):
        work.cancel_market(market_id)
    direct_vm.sender = owner
    assert work.cancel_market(market_id) == "CANCELLED"
    assert work.get_balance(_hex(owner)) == str(CLAIM)
    assert work.get_balance(_hex(alice)) == str(CLAIM)
    assert work.get_balance(_hex(bob)) == str(CLAIM)
    with direct_vm.expect_revert("Only an OPEN market"):
        work.cancel_market(market_id)
    direct_vm.sender = alice
    with direct_vm.expect_revert("Betting is closed"):
        work.bet(market_id, "0", str(5 * GEN))


def test_adjudicate_guards(direct_vm, work, direct_alice, direct_bob):
    market_id, who = _setup_market(direct_vm, work, direct_alice, direct_bob)
    owner = who[0]
    direct_vm.sender = owner
    with direct_vm.expect_revert("Only a PROPOSED market"):
        work.adjudicate(market_id)
    work.propose_outcome(market_id, "0", GOOD_EVIDENCE)
    _mock_verdict(direct_vm, "OUTCOME|0")
    work.adjudicate(market_id)
    with direct_vm.expect_revert("Only a PROPOSED market"):
        work.adjudicate(market_id)
    work.settle(market_id)
    with direct_vm.expect_revert("Only an adjudicated market"):
        work.settle(market_id)


def test_bad_llm_format_fails_before_write(direct_vm, work, direct_alice, direct_bob):
    market_id, who = _setup_market(direct_vm, work, direct_alice, direct_bob)
    owner = who[0]
    direct_vm.sender = owner
    work.propose_outcome(market_id, "0", GOOD_EVIDENCE)
    _mock_verdict(direct_vm, "Trump won, obviously!")
    with direct_vm.expect_revert():
        work.adjudicate(market_id)
    assert work.get_market(market_id)["status"] == "PROPOSED"


def test_validator_disagreement_is_detected(direct_vm, work, direct_alice, direct_bob):
    market_id, who = _setup_market(direct_vm, work, direct_alice, direct_bob)
    owner = who[0]
    direct_vm.sender = owner
    work.propose_outcome(market_id, "0", GOOD_EVIDENCE)
    _mock_verdict(direct_vm, "OUTCOME|0")
    assert work.adjudicate(market_id) == "OUTCOME|0"
    direct_vm.clear_mocks()
    _mock_verdict(direct_vm, "OUTCOME|1")
    assert direct_vm.run_validator() is False


def test_witness_kept_after_verdict(direct_vm, work, direct_alice, direct_bob):
    market_id, who = _setup_market(direct_vm, work, direct_alice, direct_bob)
    owner = who[0]
    direct_vm.sender = owner
    work.propose_outcome(market_id, "0", GOOD_EVIDENCE)
    _mock_verdict(direct_vm, "OUTCOME|0")
    work.adjudicate(market_id)
    work.submit_witness(market_id, "Note: the evidence named the deciding source.")
    market = work.get_market(market_id)
    assert market["status"] == "ADJUDICATED"
    assert market["verdict"] == "OUTCOME|0"
    assert "WITNESS|Note:" in market["history"]
