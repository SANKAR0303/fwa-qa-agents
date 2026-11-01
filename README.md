# fwa-qa-agents

Multi-agent framework for automated firmware validation — build detection, device flashing, test execution, and LLM-powered failure triage.

Runs end to end on a laptop with no hardware and no API keys.

## Why it is built this way

Most of firmware validation is deterministic: detect a build, flash it, boot the device, run a suite, collect results. That work belongs in a pipeline, not in an LLM agent — the same input should produce the same output every time, and a language model is the wrong tool for a job that needs repeatability.

Judgement is where a model earns its place. When forty tests fail, deciding which of them are the *same* problem is reading unstructured log text and inferring a cause. That is the part this framework gives to an agent.

So the design is a **deterministic spine with agents at the judgement points**: