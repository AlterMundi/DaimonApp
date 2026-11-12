"""Test-only signed Matrix owner for the actual Core/App receiving journey.

Uses the existing group fixture and synthetic keys; no installed body binding,
external peer, real provider, account or service is opened. Lifetime belongs to
its parent test process. One report remains in the test-owned temporary directory.
"""
import importlib.util
import json
from pathlib import Path
import sys
import time

app = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(app / "scripts"))
spec = importlib.util.spec_from_file_location("app_matrix_owner_fixture", app / "tests/matrix_execution.py")
fixture = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = fixture
spec.loader.exec_module(fixture)
from daimon_matrix.execution_instruction import digest
from daimon_matrix.review_runner import ProviderCostBound
from matrix_execution import prepare_native_account_owner, serve_native_account_owner
from tests.test_execution_instruction import proof, verifier

start = json.loads(sys.stdin.readline())
case = fixture.AdapterTests()
case.setUp()
report = Path(sys.argv[1])
try:
    # Sign the actual complete-request ceiling, including native context/tools;
    # the predecessor16KiB token allocation did not cover its1MiB transport grant.
    state = case.funded_original(native_attempts=2, epoch=int(time.time()),
                                max_input_tokens=1024 * 1024)
    selected = case.native_funding_selection(state)
    registration = selected["registration"] | {
        "native_thread_id": start["thread_id"], "max_request_bytes": 1024 * 1024,
        "source_mode": "app_owned_inbox", "source_channel": "tribe",
        "instruction_sha256": state.instruction.sha256,
    }
    payload = dict(
        schema="execution/provider-cost-bound/v1", principal=state.instruction.principal,
        store_id=state.store.store_id, registration_sha256=digest(registration),
        route="isolated-fake", unit="synthetic-charge", expires=state.instruction.end,
        max_input_tokens=state.instruction.max_input_tokens,
        max_output_tokens=state.instruction.max_output_tokens,
        input_price=0, output_price=0, fixed_charge=30,
    )
    bound = ProviderCostBound.verify(payload,
        proof(state.key, "approve", payload, "receiving-cost"), verifier(state.key))
    owner = prepare_native_account_owner(
        state.store, state.instruction, state.purpose,
        thread_id=start["thread_id"], parent_allowance=start["parent_allowance"],
        cost_bound=bound, registration=registration,
        work_id=None, host_source={"channel_id": "tribe", "message_id": state.source["event_id"],
                "message_hash": state.source["content_hash"], "local_execution_id": 42},
        read_message=state.controller.read_message,
    )
    observations = []

    def sign_synthetic_usage(request):
        params = request["observation"]
        observations.append(params)
        usage = dict(schema="execution/usage/v1", store_id=state.store.store_id,
                     principal=state.instruction.principal, cycle_id=owner._context.cycle.cycle_id,
                     operation_id=params["attemptId"], actual=8)
        return {"usage": usage, "proof": proof(state.key, "approve", usage,
            "receiving-usage-" + params["attemptId"])}

    serve_native_account_owner(owner, sys.stdin.fileno(), sys.stdout.fileno(),
                               receipt_provider=sign_synthetic_usage)
    cycle = state.store.cycle_status(owner._context.cycle.cycle_id)
    report.write_text(json.dumps({"cycle": cycle, "funding": state.store.funding_status("episode"),
                                 "observations": observations, "synthetic": True}))
except BaseException:
    import traceback
    report.write_text(json.dumps({"synthetic": True, "error": traceback.format_exc()}))
    raise
finally:
    case.doCleanups()
