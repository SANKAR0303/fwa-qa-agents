# fwa-qa-agents

Multi-agent framework for automated firmware validation — build detection, device flashing, test execution, and LLM-powered failure triage.

Runs end to end on a laptop with no hardware and no API keys.

## Why it is built this way

Most of firmware validation is deterministic: detect a build, flash it, boot the device, run a suite, collect results. That work belongs in a pipeline, not in an LLM agent — the same input should produce the same output every time, and a language model is the wrong tool for a job that needs repeatability.

Judgement is where a model earns its place. When forty tests fail, deciding which of them are the same problem is reading unstructured log text and inferring a cause. That is the part this framework gives to an agent.

So the design is a deterministic spine with agents at the judgement points:

    src/fwa_qa/
    ├── devices/     device abstraction + simulated gateway
    ├── core/        event types and the pub/sub bus
    ├── pipeline/    build watcher, flasher, suite runner  (deterministic)
    └── agents/      triage agent                          (LLM-backed)

Components never call each other. They publish events to a bus and subscribe to the ones they care about, so adding a new domain agent means subscribing to an existing event rather than editing existing code.

## Running it

Requires Python 3.10+ and Ollama for the triage agent.

    pip install -r requirements.txt
    ollama pull qwen2.5:7b

    mkdir builds
    touch builds/gateway-fw-wifi7-2.4.1.bin
    python -m fwa_qa.cli

The simulated device accepts flash commands, emits plausible boot logs, and injects failures at a configurable rate, so the whole pipeline runs without hardware. Real devices implement the same `DUT` interface.

## Sample output

    BuildDetected      builds/gateway-fw-wifi7-2.4.1.bin -> 2.4.1 (wifi7)
    FlashCompleted     success, 45.2s
    DeviceReady        firmware 2.4.1
    SuiteStarted       wifi_basic, 8 cases
    SuiteFinished      5 passed, 3 failed

    --- triage report (qwen2.5:7b) ---

    [error] 2.4GHz Wi-Fi interface issues preventing client association and DHCP lease
      cause: Potential hardware or driver issue with wlan0 interface
      cases: WIFI-001, WIFI-004, WIFI-006
      confidence: 80%

Three failures, one root cause — grouped by the agent rather than by a human reading logs.

## Design notes

**The device interface is the seam.** `DUT` defines six operations. `SimulatedDUT` implements them in-process; an SSH-backed implementation for real hardware changes nothing above it.

**The simulator is seeded.** Same seed, same run. Non-deterministic test infrastructure is not worth building.

**Triage degrades rather than fails.** If the model is unreachable or returns unparseable JSON, the agent emits one cluster per failure and says so. A worse report beats no report.

**Suites are data.** Test cases live in YAML, so adding one does not mean writing Python.

## Status

Working vertical slice: one device, one suite, one agent. Planned: additional domain agents (5G, mesh, stability), parallel device pools, and a report artifact.

## License

MIT