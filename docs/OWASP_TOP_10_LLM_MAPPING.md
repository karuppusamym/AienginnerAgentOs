# OWASP Top 10 for LLMs Mapping

This document outlines how DataPilot Agent OS addresses the vulnerabilities detailed in the [OWASP Top 10 for Large Language Model Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/).

## LLM01: Prompt Injection
**Risk:** Attackers manipulate the LLM through crafted inputs, causing it to execute unintended actions or ignore previous instructions.
**How DataPilot handles it:** 
- **Separation of instructions and data:** User prompts are kept separate from the system instructions.
- **Bounded execution:** The local runner explicitly restricts write and DDL operations, mitigating the impact even if an injection occurs.
- **Guardrails:** All generated SQL is validated locally before execution. Read-only previews run in isolated transactions.
- **Approvals:** Risky objectives require human approval.

## LLM02: Insecure Output Handling
**Risk:** Accepting LLM output without scrutiny can lead to XSS, SSRF, privilege escalation, or remote code execution.
**How DataPilot handles it:**
- **Strict output validation:** Generated SQL is parsed and verified to be a single `SELECT` or `WITH` statement before any execution occurs.
- **Restricted tools:** Agents are restricted to calling a predefined set of bounded tools.
- **Sandboxed UI rendering:** Markdown and chart rendering in the UI is sanitized to prevent XSS.

## LLM03: Training Data Poisoning
**Risk:** Tampering with the data used to train or fine-tune models to introduce vulnerabilities or biases.
**How DataPilot handles it:**
- **No autonomous self-learning:** DataPilot does not autonomously retrain models or automatically update prompts based on user feedback. 
- **Human review:** Any feedback or evaluation requires human review before it alters system behavior.

## LLM04: Model Denial of Service
**Risk:** Attackers cause resource-heavy operations on LLMs, leading to service degradation or high costs.
**How DataPilot handles it:**
- **Tool budget:** Agent loops are strictly capped (e.g., maximum of 12 tool calls).
- **Query caching:** Governed queries are deterministically cached based on exact context signatures to reduce redundant model calls.
- **Timeouts and row limits:** Configurable limits on generated queries and tools prevent heavy resource consumption.

## LLM05: Supply Chain Vulnerabilities
**Risk:** Vulnerabilities in third-party datasets, pre-trained models, and plugins.
**How DataPilot handles it:**
- **Model provider registry:** Only approved and tested model providers configured by the administrator can be used.
- **Local offline fallback:** The system supports a local deterministic fallback if external models are compromised or unavailable.

## LLM06: Sensitive Information Disclosure
**Risk:** The LLM inadvertently reveals confidential data, PII, or proprietary information in its responses.
**How DataPilot handles it:**
- **Project isolation:** Assets, tools, and conversations are scoped strictly to projects. Users can only query data they have access to.
- **Redaction:** Governance telemetry integration (e.g., AgentGuard) supports redacting PII or sensitive content from prompts before logging them.

## LLM07: Insecure Plugin Design
**Risk:** LLM plugins that have insecure inputs or inadequate access control, leading to malicious exploitation.
**How DataPilot handles it:**
- **Typed tool contracts:** Internal and external query tools are bounded by strict JSON Schema validations.
- **Client grants:** External AI clients can only discover and invoke tools explicitly granted to them.
- **Approval fallback:** Tools performing state-changing actions require explicit human approval workflows.

## LLM08: Excessive Agency
**Risk:** Granting the LLM functionality, permissions, or autonomy beyond what is necessary.
**How DataPilot handles it:**
- **Bounded autonomy:** Planners operate within constrained Autonomy Levels.
- **Approval boundaries:** Actions like deploying pipelines, scheduling ingestion, and executing writes are blocked pending human review.
- **Read-only default:** Database connectors are set to read-only by default.

## LLM09: Overreliance
**Risk:** Over-trusting LLM outputs without critical oversight, leading to misinformation or flawed decisions.
**How DataPilot handles it:**
- **Explainability:** The "Source and result" panel shows exactly what metadata, context, and semantic terms were used to generate the output.
- **Human-in-the-loop:** Critical actions require approval. Quality rules surface failure samples for review.
- **Evaluation replay:** Evaluation sets are used to replay and score agent versions against known baselines.

## LLM10: Model Theft
**Risk:** Unauthorized access, copying, or exfiltration of proprietary LLMs.
**How DataPilot handles it:**
- **External integration:** DataPilot relies on secured APIs for external models, preventing direct access to model weights.
- **Governance telemetry:** Real-time monitoring and export of model calls help detect abnormal extraction patterns.
