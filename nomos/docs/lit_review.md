# Literature Review

*Background context and related work for the logic-first domain design methodology.*

This document situates the methodology described in
[methodology.md](methodology.md) within the existing literature on agent
benchmarks, logic programming for policy, formal methods for LLM-generated
content, constraint-based test generation, and adversarial agent testing.

Built from 42 curated papers gathered by parallel research agents
covering 6 topic areas:

- **Conversational and tool-use LLM agent benchmarks** — The conversational/tool-use agent benchmark literature is converging on a narrow design pattern: a simulated user, a tool-equipped agent, a backing database, and a per-task or per-environment success oracle. The leading enterprise-flavored benchmarks (τ-bench, τ²-bench) already pick deterministic DB-endstate equality as their oracle, which is the strongest pillar to build on, but their policies remain prose and their tasks remain hand-authored Python or JSON. Adjacent benchmarks (AgentBench, WebArena, OSWorld) ship one bespoke checker per task or environment, while ToolBench and GAIA rely on LLM-judge or exact-string scoring respectively. A very recent paper (LOGIGEN, 2026) independently arrives at the same insight as our methodology — compile policy to hard logical constraints and use state equivalence as the oracle — which both validates the direction and clarifies our differentiation: ASP/Clingo as first-class policy semantics, separable Verify/Solve/Generate operations, and structured JSON intent specs cross-validated against an upstream tau2-bench domain.
- **Answer Set Programming and logic programming for policy, business rules, compliance, and regulatory reasoning** — This slice of the literature shows a long tradition of using Answer Set Programming and goal-directed ASP (s(CASP)) to give faithful, machine-checkable semantics to policy languages - from XACML access control to statutory law, defeasible legal reasoning, and Declare-style business process constraints. Recent 2024-2026 work pushes this approach into the LLM agent space: tools like ShieldAgent and frameworks like LOGIGEN explicitly mine or compile policies into logic circuits to verify agent behavior, mirroring the Verify/Solve/Generate split our methodology builds in at design time. Together these references support three design choices in our methodology: (i) ASP/Clingo is a well-validated substrate for encoding policy with exceptions and defeasibility; (ii) the same logic program can serve verification, ground-truth solving, and task generation; and (iii) the broader community is converging on declarative policy + solver-checked behavior as the path to trustworthy agent benchmarks, which strengthens the case for grounding domains like a tau-bench airline slice in ASP rather than prose.
- **Declarative policy languages (Datalog, OPA/Rego, Cedar, Catala, defeasible-logic legal DSLs)** — Declarative policy languages provide direct prior art for the methodology's policy/contract layer: Cedar (OOPSLA 2024) and its verification-guided development companion show that intentionally restricting policy expressiveness yields decidable analyses (equivalence, refactoring safety) mechanized in Lean - the same trade the ASP layer makes when it picks Clingo over a Turing-complete world model. Catala and the CCLAW L4 / Answer Set Programming line establish that ambiguous source policy is best re-expressed in a logic with defaults and priorities, exactly the move the 6-layer design makes when translating prose policy into ASP world rules and an agent contract. Recent LLM-to-policy work (Prose2Policy for Rego, Horner et al. for Defeasible Deontic Logic) shows the prose-to-spec translation step is now a practical engineering pattern, including auto-generation of positive and negative tests that closely mirror the methodology's Generate operation. Together these papers let the methodology be positioned as "ASP is to benchmark domains what Cedar/Catala are to authorization and statute" - a declarative substrate chosen so that Verify, Solve, and Generate are well-defined logical operations rather than ad hoc engineering.
- **Formal methods, model checking, and symbolic reasoning applied to LLM agents and benchmark evaluation** — A rapidly growing body of work in 2024-2026 applies formal methods to LLM agents in two complementary ways: (1) using solvers (SMT, ASP, theorem provers, model checkers) to verify or constrain agent behavior at runtime, and (2) using LLMs to author formal artifacts (PDDL domains, ASP programs, SMT-LIB constraints) that downstream solvers then exploit for guarantees. Several papers explicitly target tau-bench-style policy-compliant tool agents (Winston et al. on solver-aided tau-bench verification, AgentSpec, VeriGuard), validating the relevance of declarative specifications to the same domain class our methodology targets. Foundational work (SatLM) establishes the broader pattern of having an LLM emit a declarative spec and offloading correctness to a solver — exactly the architectural move our Solve/Verify operations make with Clingo. Notably absent is prior work that uses ASP specifically to design benchmark domains and prove task uniqueness, which is the gap our methodology fills.
- **Constraint-based test generation, model-based testing, and property-based testing for software with complex business rules** — Constraint-based and property-based testing has a long lineage of designing test generators from declarative specs rather than handcrafting examples, which is directly relevant to our methodology of generating LLM-agent benchmark tasks from ASP/Clingo specs. Foundational work (QuickCheck, Korat, Quviq stateful PBT) established the pattern: write an executable specification (properties, predicates, or a state machine), let a search/solver synthesize structurally valid test inputs, and use the spec itself as an oracle. Modern industrial-practice studies (Goldstein et al., ICSE 2024) document the limits of ad-hoc generators and explicitly call for better distribution control and coverage feedback, which our intent-JSON + ASP design directly addresses. Recent LLM-era work (PGS, Agentic PBT, and especially LOGIGEN) shows that the same recipe is now being ported to LLM evaluation, but mostly with ad-hoc oracles or DB constraints rather than full logical specifications, leaving open the niche our ASP-based Verify/Solve/Generate methodology occupies. Together these papers let us frame our contribution as: stateful property-based testing for LLM agents, with ASP replacing handwritten state-machine models as the executable spec and oracle.
- **Adversarial robustness, behavioral testing, and red-teaming of LLM agents** — The adversarial-robustness literature for LLM agents has crystallized into three concrete failure modes our methodology must be able to express and verify: (1) direct user manipulation of policy-adherent agents (tau-break / CRAFT), (2) indirect prompt injection via tool outputs (InjecAgent, AgentDojo, ASB), and (3) outright harmful-task compliance (AgentHarm, Agent-SafetyBench). The key methodological takeaway for an ASP/Clingo-based benchmark designer is that nearly every state-of-the-art adversarial benchmark uses environment-state checks (formal utility functions in AgentDojo, DB-state diffs in tau-bench) rather than LLM judges to verify behavior, because LLM judges can be co-manipulated by the same attack. This is structurally identical to what our Verify/Solve operations do, but extended with negative test cases where the ground-truth "correct" final state is "no change" / "refusal." Of particular relevance, the tau-break work runs directly on tau-bench's airline/retail domains and shows that even strong agents fold under policy-aware persuasion, which is exactly the failure mode an ASP-encoded policy could in principle make tractable to test exhaustively. Together these works justify treating refusal-correctness tasks as first-class citizens in our intent JSON schema and motivate using ASP to certify that a manipulative dialogue should provably not reach a policy-violating final state.

All citations resolve to [`references.bib`](references.bib). Inline citations
use the BibTeX key in square brackets, e.g. `[yao2024taubench]`.

---

# Literature Review

## 1. Conversational agent benchmarks (the immediate context)

The methodology developed in this work is situated within a rapidly maturing line of benchmarks for tool-using, multi-turn LLM agents. The most direct upstream is τ-bench [yao2024taubench], which establishes the tool-agent-user paradigm in customer-service domains (retail, airline), evaluates by comparing the post-conversation database state to a hand-annotated goal state, and introduces the pass^k reliability metric. τ-bench is also our primary cross-validation target: the 8/8 result on its airline cancellation slice is meaningful precisely because the upstream tasks were authored independently of our methodology. Its two design choices — DB-state equality as the success criterion and a natural-language policy document — together motivate the gap our six-layer architecture aims to fill: the success criterion is already declarative-in-spirit, but the policy is prose and the tasks are imperative.

τ²-bench [barres2025tau2bench] extends this lineage to a dual-control Dec-POMDP setting where both the agent and the simulated user can mutate shared state, and introduces a compositional task generator with controlled complexity in a telecom domain. That generator is the closest existing analogue to our Generate operation, although tasks remain Python-encoded rather than declarative.

Other major agent benchmarks span the design space against which our work positions itself. AgentBench [liu2023agentbench] is the canonical example of the per-environment hand-crafted-evaluator style: each of its eight environments encodes policy implicitly in bespoke checker code. ToolLLM/ToolBench [qin2023toolllm] takes the opposite tack, using an LLM-judge over thousands of real APIs. WebArena [zhou2023webarena] and OSWorld [xie2024osworld] use execution-based, programmatic checkers per task — making correctness verifiable but scaling human effort linearly in tasks. GAIA [mialon2023gaia] represents the open-world end of the spectrum, with hand-annotated string answers for exact-match scoring. The recurring pattern across all of these is that the "oracle" is either an LLM judge, a hand-written checker per task, or a hand-annotated gold answer — none expose the policy itself as a declarative artifact.

LOGIGEN [zeng2026logigen] is the closest contemporary work and is discussed in depth in Section 6.

## 2. Logic programming and declarative policy

The intellectual core of our methodology — encoding world rules and an agent contract in ASP/Clingo — sits within a long tradition of treating policy and law as formal, executable artifacts. The richest body of precedent comes from legal and access-control reasoning.

s(LAW) [arias2024slaw] uses s(CASP), a goal-directed Constraint ASP system, to encode administrative policy (Madrid's student admission rules) with explicit patterns for ambiguity and discretion, and produces natural-language justifications. Structurally this is the same task as our Solve operation: derive a ground-truth conclusion from a declarative spec. The s(CASP) pattern library for discretion is a useful precedent for the open-vocabulary classification problem we encountered ("does this fall under an insurance-covered reason?"), which we ultimately handled via external predicates.

Blawx [morris2023blawx] deploys s(CASP) for real Canadian privacy and policy reasoning behind a non-programmer-friendly Blockly front-end, and supports hypothetical and abductive queries — operations directly analogous to our Verify step probing whether a policy admits a unique trajectory. Catala [merigoux2021catala] takes the rules-as-code idea in a different direction, building a verified compiler over Sarah Lawsky's default logic in which statutes' general-rule/exception structure maps to dedicated language constructs; the compiler exposed a real bug in the French family-benefits implementation. Catala provides the strongest precedent for the methodological move from prose policy to a logic-with-defaults, but it pointedly avoids ASP's nonmonotonic negation.

The cleanest historical analog of our methodology is XACML 3.0 in ASP [ramli2012xacml]: a real-world policy language (access control) is given a faithful ASP encoding so that an off-the-shelf solver can verify global properties — completeness, redundancy, conflicts, refinement, reachability, usefulness. That property catalog maps almost one-to-one onto the checks our Verify operation performs on a benchmark domain. Earlier work [abiteboul2016collaborative] formalizes access control as Datalog and studies decidability of information leakage, providing the theoretical grounding for why declarative policy gives you decidable analyses that imperative policy code does not.

On defeasibility specifically, two strands are relevant. One [lam2022defeasible] studies legal norms with priority and override modifiers and shows transformations to ASP whose stable models capture intended legal conclusions. A closely related line [lim2022defeasibleasp] translates the L4 legal DSL to ASP and explicitly compares ASP against SMT as the policy back-end. Defeasibility is precisely the awkward part of τ-bench-style policies (cancellation interacting with status, fare class, the 24-hour rule, and agent overrides), and these papers support our choice of ASP over plain Datalog or Horn clauses.

Two more recent points of comparison sharpen the design space. Cedar [cutler2024cedar] deliberately restricts an authorization DSL so policies have a sound-and-complete SMT encoding, with key properties mechanized in Lean — trading expressiveness for decidability, structurally the same trade we make with ASP. The companion paper on Verification-Guided Development [disselkoen2024howcedar] describes the engineering loop of writing an executable formal model, proving properties on it, and using differential testing to keep the production implementation in sync; the 25 bugs found are evidence of how much underspecification this loop catches. At the other extreme, policy-as-type [fuchs2025policyastype] argues access control should live in a dependently typed language, making policy violations type errors — useful as the maximum-expressiveness end of the spectrum against which decidable model-finding (ASP) is the right pragmatic compromise for benchmark domains.

## 3. Formal methods for LLM-generated content

Several recent systems sit between LLMs and formal solvers in ways that parallel pieces of our methodology.

SatLM [ye2023satlm] is the foundational architectural template for our Solve operation: prompt the LLM to emit a declarative specification rather than an imperative solution, then derive the answer with a solver. SatLM shows this delivers correctness guarantees relative to the parsed spec; we adopt the same separation of concerns but in the benchmark-construction setting, where Clingo derives the unique final database state from world rules plus a JSON intent. CLMASP [lin2024clmasp] demonstrates the same labor split in robotics — LLM skeleton plan, ASP refinement using action preconditions/effects — and lifts VirtualHome executability from under 2% to over 90%. This is concrete empirical backing that Clingo-derived consequences are reliable enough to serve as ground truth.

A related cluster targets policy compliance and safety for tool-using LLM agents directly. ShieldAgent [chen2025shieldagent] extracts verifiable rules from policy documents and performs probabilistic logic verification at inference time; it is exactly the failure mode our up-front declarative encoding is designed to bypass. Solver-aided verification [winston2026solveraided] translates tool-use policies to SMT-LIB-2.0 and intercepts τ-bench tool calls at runtime, using Z3 for compliance — same domain class as us, same fundamental move (formalize policy, hand correctness to a solver), but their target is runtime tool-call compliance, while ours is design-time benchmark correctness. VeriGuard [miculicich2025veriguard] splits offline policy synthesis-and-verification from online monitoring, structurally mirroring our split between authoring-time formal artifacts and runtime evaluation. AgentSpec [wang2025agentspec] is a DSL for runtime constraints with millisecond-scale enforcement. Formal-LLM [li2024formalllm] uses a pushdown automaton to bound LLM plan generation. Neuro-symbolic instruction-following verification [su2026nsvif] formalizes the LLM-as-formalizer plus solver-as-judge pipeline at a per-output granularity.

Two LLM-to-policy translation pipelines are particularly close to the prose-to-spec problem we sidestep by authoring intent in structured JSON. One [horner2025legaldll] translates regulation to Defeasible Deontic Logic with a refinement loop, evaluated on Australian telecom regulation. Another [gupta2026prose2policy] is an end-to-end pipeline that generates Rego from prose with 95.3% compile rate and auto-generated positive/negative tests. Both show that mature policy-as-code targets are now being produced from prose with a Verify-and-Test discipline; their auto-generated test pairs align closely with our Generate operation.

## 4. Constraint-based test and scenario generation

Our Generate operation has its strongest precedents in property-based testing (PBT) and constraint-based test-input generation, well before LLMs entered the picture.

QuickCheck [claessen2000quickcheck] is the foundational reference: programmers write executable universally-quantified properties, the tool generates random inputs from typed generators, and counterexamples are automatically shrunk. The "specification as executable property" idea is exactly what motivates our Verify/Solve operations, though our ASP world rules synthesize ground-truth final states deductively rather than checking randomly drawn inputs. Korat [boyapati2002korat] is the more direct ancestor of our Generate operation: a declarative predicate (repOK) plus a finitization drives exhaustive enumeration of non-isomorphic valid structures, which are then run against the method using its postcondition as oracle. The pre/postcondition split also mirrors our agent-contract layer used as the policy oracle. QuickREST [karlsson2020quickrest] is the closest analog outside LLM agents: a structured API spec (OpenAPI) drives both inputs and oracle, with low engineering effort, on industrial REST services — an existence proof that spec-driven generation-plus-oracle is a proven pattern at the API layer we operate on.

Stateful PBT is the pre-LLM analog of multi-turn agent benchmarks. The Quviq QuickCheck deployment at Ericsson [arts2006quviq] used a state-machine model of a Media Gateway protocol, with call sequences as test cases and pre/post-conditions as oracles, uncovering specification ambiguities and real faults. This treats the system under test as a state machine whose transitions are tool calls and whose invariants encode business policy — precisely the abstraction our six layers formalize.

A recent empirical study [goldstein2024pbtpractice] of 30 industrial PBT users at Jane Street documents the real frictions of writing generators, controlling distributions, and getting coverage feedback. These frictions justify our move from ad-hoc random generation to declarative ASP plus structured intent JSON, where difficulty is a parameter of the spec rather than a property emergent from hand-tuned generators.

PBT is now beginning to fuse with LLMs from both sides. PGS [he2025pgs] uses a Generator/Tester LLM loop with property-based tests as the validation engine, showing 23–37% relative pass@1 gains over TDD baselines — recent evidence that high-level declarative properties beat enumerated I/O pairs when judging LLM behavior. Agentic PBT [maaz2025agenticpbt] runs the other direction: an LLM agent infers properties from code and docs, synthesizes Hypothesis tests, and produces actionable bug reports across 100 Python packages, with 56% report validity. The latter is direct evidence that we still need a non-LLM oracle (Clingo) on the spec side to avoid the failure mode in which tests and code share flaws.

LOGIGEN [zeng2026logigen] belongs to this section as well as Section 1 — see Section 6.

## 5. Adversarial and behavioral testing

Although our worked examples are positive-task benchmarks, the adversarial-testing literature shapes the design space we must accommodate. τ-break and CRAFT [nakash2025taubreak] live in the exact τ-bench substrate we cross-validate against and operationalize "manipulative user" as a first-class evaluation axis using policy-aware persuasive strategies. Because CRAFT reasons explicitly about policy text, an ASP-encoded policy makes red-team success decidable in principle: a task's ground-truth final state under Solve becomes "no policy-violating action taken," and Verify can prove uniqueness of that null/refusal outcome.

AgentHarm [andriushchenko2024agentharm] establishes refusal-correctness as a measurable property of tool-using agents, decoupling "did the agent refuse?" from "did the agent complete?". AgentDojo [debenedetti2024agentdojo] pairs benign tasks with prompt-injection security tests and crucially checks both success and violations via formal utility functions over post-execution state, so the evaluator cannot be co-attacked by the same injection. That utility-function design is the empirical analogue of Solve and motivates lifting it to declarative ASP. InjecAgent [zhan2024injecagent] gives a structured taxonomy of indirect-injection attack intents (direct user harm vs. exfiltration) over 17 user tools and 62 attacker tools. Agent-SafetyBench [zhang2024agentsafetybench] documents that no current agent exceeds 60% safety across 8 risk categories and isolates root causes (lack of robustness, lack of risk awareness) that motivate our preference for declarative, machine-verifiable policy. ASB [zhang2025asb] provides a coverage map enumerating 10 attack vectors — direct/indirect injection, memory poisoning, plan-of-thought backdoors, mixed attacks — that any complete agent methodology should express. Each attack family becomes, in our terms, a class of adversarial intents the intent JSON must support and Verify must label as ground-truth-refuse.

## 6. Synthesis — what's our position in this landscape

The most honest statement of our position is that none of the three operations the methodology offers — Verify, Solve, Generate — is individually unprecedented, but their integration around a declarative ASP semantics specifically for benchmark-domain design is, to our knowledge, new.

**The closest precedent is LOGIGEN** [zeng2026logigen]. It shares the three core ideas — hard-compiled policy, state-based verification, and synthesized verifiable tasks — and applies them to the τ²-Bench substrate, yielding a 20k-task training corpus across eight domains that lifts a 32B model from 40.7% to 79.5% on τ²-Bench. We must be clear that LOGIGEN got there first as a working system at scale. The genuine differences are: (i) LOGIGEN compiles policy to database constraints, whereas we use ASP/Clingo as a first-class non-monotonic semantics for the policy itself, which matters for defeasibility (exception/override structures pervasive in τ-bench's airline policy); (ii) LOGIGEN's Verify is post-hoc state equivalence on candidate traces, while ours proves *task uniqueness* — that the spec admits exactly one final state — *before* any agent or trace exists; (iii) LOGIGEN uses an Architect/Set-Designer/Explorer LLM pipeline, while our intent is JSON-structured by the author, with the LLM out of the formal loop. The contributions are complementary rather than competing: LOGIGEN optimizes for training-data scale, we optimize for design-time soundness guarantees on a small number of curated tasks. Anyone reading our work should also read LOGIGEN.

**The closest ASP-for-policy precedent** that exposes the same operation set is XACML-in-ASP [ramli2012xacml]. Their property catalog (completeness, conflict, redundancy, refinement, reachability) is essentially the Verify side of our methodology, applied to a real authorization standard rather than to a benchmark domain. We were not first to use ASP to mechanically verify global properties of a real-world policy. What's novel relative to [ramli2012xacml] is the *re-use* of the same declarative encoding for two further operations — Solve (derive D* from spec alone) and Generate (sample tasks at controlled difficulty) — and the application context (benchmark construction for LLM agents rather than offline policy administration).

**The closest legal-ASP precedents** [arias2024slaw, morris2023blawx, lam2022defeasible, lim2022defeasibleasp] established that ASP and s(CASP) can carry administrative policy and defeasible legal rules, including with discretion patterns and rule-modifier overrides. We borrow that machinery. We did not invent ASP-based defeasibility or discretion handling; we are reusing established techniques in a new domain.

**The closest formal-policy DSL precedents** are Catala [merigoux2021catala] and Cedar [cutler2024cedar, disselkoen2024howcedar]. Catala established the value of literate, exception-prioritized formalization for ambiguous source policy and demonstrated that this style finds real bugs in source — paralleling our discovery of underspecification in τ-bench airline tasks. Cedar established the deliberate-restriction-for-analyzability trade and the Verification-Guided Development engineering pattern. Our 8/8 airline cross-validation is essentially a differential check in the VGD sense.

**The closest test-generation precedent** is Korat [boyapati2002korat]: a declarative predicate plus a finitization driving exhaustive enumeration of valid test scenarios. Our Generate operation is structurally the Korat pattern applied to multi-turn agent tasks rather than to data-structure inputs.

**The closest solver-aided agent precedent**, in the exact same domain class, is [winston2026solveraided]: it formalizes τ-bench tool-use policies in SMT-LIB and uses Z3 to check tool calls at runtime. They were first to use a solver to enforce τ-bench policy. What we add is a different target — design-time benchmark correctness rather than runtime call-blocking — and a different formal substrate (ASP rather than SMT), chosen because non-monotonic reasoning and answer-set enumeration are natural fits for the uniqueness questions we ask.

Given all of the above, what is genuinely new about our methodology?

First, **the integration**. No prior work, to our knowledge, exposes Verify, Solve, and Generate as three operations over a *single* declarative core in the service of benchmark domain *design*. LOGIGEN [zeng2026logigen] integrates the same three ideas but for training data generation, with DB constraints and an LLM-driven generator; XACML-in-ASP [ramli2012xacml] integrates Verify-style checks only; Cedar integrates Verify-style equivalence checks plus differential testing; SatLM [ye2023satlm] and CLMASP [lin2024clmasp] use the LLM-emits-spec-then-solver split per query, not as a domain authoring operation. Our claim is that ASP/Clingo is expressive enough to carry all three operations simultaneously on τ-bench-style domains.

Second, **uniqueness as the central design-time property**. The benchmark literature treats correctness as a per-task check, evaluated against a hand-annotated goal [yao2024taubench, zhou2023webarena, xie2024osworld] or a per-task script [liu2023agentbench, mialon2023gaia]. Even LOGIGEN's verification is post-hoc state equivalence. We make *uniqueness of the intended outcome under the rules* the property that Verify proves before tasks are released, which directly addresses the pass^k reliability concern [yao2024taubench] at its source.

Third, **structured intent JSON instead of LLM-mediated translation**. Recent prose-to-policy pipelines [horner2025legaldll, gupta2026prose2policy, chen2025shieldagent] and the LOGIGEN Architect place an LLM between source policy and formal target. We instead require the domain author to write intent as JSON against a fixed schema, accepting a heavier authoring burden in exchange for keeping the LLM out of the formal verification loop. This is a deliberate methodological stance, not a novel technique.

Fourth, **the specific ASP adaptations needed to handle τ-bench-class policies**. External predicates for open-vocabulary classification (the "insurance covers this reason" case), composite identifiers, and positional sub-entities are practical contributions documented through our airline retrofitting. None are theoretically novel — external predicates are a standard Clingo facility, and composite keys are standard practice — but their necessity for retrofitting an existing, prose-authored benchmark is a finding worth reporting.

What we explicitly do *not* claim: we do not claim novelty for ASP-as-policy [ramli2012xacml, arias2024slaw, morris2023blawx, lam2022defeasible, lim2022defeasibleasp]; for declarative-spec-plus-solver as an LLM architecture [ye2023satlm, lin2024clmasp]; for property-based or constraint-based test generation [claessen2000quickcheck, boyapati2002korat, karlsson2020quickrest, arts2006quviq]; for state-based agent evaluation [yao2024taubench, debenedetti2024agentdojo]; or for logic-driven generation of verifiable agentic tasks at scale [zeng2026logigen]. Our contribution is the deliberate composition of these ideas into a domain-design methodology for closed-world tool-agent benchmarks, validated end-to-end on a greenfield retail_returns domain and cross-validated against an authored τ-bench slice without modification.

---

## References

Full bibliography in [`references.bib`](references.bib). Inline references in
this document use the citation_key form. 42 unique entries.

- `[abiteboul2016collaborative]` Serge Abiteboul, Pierre Bourhis, Victor Vianu (2016). *A Formal Study of Collaborative Access Control in Distributed Datalog*. (ICDT 2016)  
  [https://cseweb.ucsd.edu/~vianu/icdt16.pdf](https://cseweb.ucsd.edu/~vianu/icdt16.pdf)
  Formalizes access control as Datalog rules (relation-level for EDB, tuple-level for IDB) and studies decidability of information leakage - whether a peer can derive a fact it is not authorized to see - under different policy classes.

- `[andriushchenko2024agentharm]` Maksym Andriushchenko, Alexandra Souly, Mateusz Dziemian, Derek Duenas, Maxwell Lin, Justin Wang, Dan Hendrycks, Andy Zou, Zico Kolter, Matt Fredrikson, Eric Winsor, Jerome Wynne, Yarin Gal, Xander Davies (2024). *AgentHarm: A Benchmark for Measuring Harmfulness of LLM Agents*. (ICLR 2025 (arXiv:2410.09024))  
  [https://arxiv.org/abs/2410.09024](https://arxiv.org/abs/2410.09024)
  110 explicitly malicious agent tasks (440 with augmentations) across 11 harm categories (fraud, cybercrime, harassment, etc.), evaluating both whether models refuse and whether, once jailbroken, they retain multi-step tool-use capability. Finds frontier models surprisingly compliant even without jailbreaks.

- `[arias2024slaw]` Joaquin Arias, Mar Moreno-Rebato, Jose A. Rodriguez-Garcia, Sascha Ossowski (2024). *Automated legal reasoning with discretion to act using s(LAW)*. (Artificial Intelligence and Law (Springer); arXiv:2401.14511)  
  [https://arxiv.org/abs/2401.14511](https://arxiv.org/abs/2401.14511)
  Introduces s(LAW), an automated legal reasoning framework on top of s(CASP) (goal-directed Constraint ASP) that captures discretion and ambiguity in legal rules via a small set of patterns, and produces natural-language justifications. Validated by encoding the student-admission criteria of the Comunidad de Madrid.

- `[arts2006quviq]` Thomas Arts, John Hughes, Joakim Johansson, Ulf Wiger (2006). *Testing Telecoms Software with Quviq QuickCheck*. (ACM SIGPLAN Erlang Workshop 2006)  
  [https://dl.acm.org/doi/10.1145/1159789.1159792](https://dl.acm.org/doi/10.1145/1159789.1159792)
  Reports the first industrial deployment of stateful property-based testing: a state-machine model of an Ericsson Media Gateway protocol, generated call sequences as test cases, and pre/post-conditions as oracles. Uncovered specification ambiguities and real faults that motivated Ericsson's continued investment.

- `[barres2025tau2bench]` Victor Barres, Honghua Dong, Soham Ray, Xujie Si, Karthik Narasimhan (2025). *τ²-Bench: Evaluating Conversational Agents in a Dual-Control Environment*. (arXiv:2506.07982)  
  [https://arxiv.org/abs/2506.07982](https://arxiv.org/abs/2506.07982)
  Extends τ-bench to a dual-control Dec-POMDP setting in which both the agent and the simulated user can call tools that mutate a shared world state, and introduces a compositional, programmatic task generator with controlled complexity in a telecom domain.

- `[boyapati2002korat]` Chandrasekhar Boyapati, Sarfraz Khurshid, Darko Marinov (2002). *Korat: Automated Testing Based on Java Predicates*. (ISSTA 2002 (International Symposium on Software Testing and Analysis))  
  [https://dl.acm.org/doi/10.1145/566171.566191](https://dl.acm.org/doi/10.1145/566171.566191)
  Bounded-exhaustive test input generation from a Java predicate (repOK) plus a finitization. Korat searches the input space, prunes using the predicate's execution trace, and enumerates all non-isomorphic structures satisfying the spec, which are then run against the method using its postcondition as the test oracle.

- `[chen2025shieldagent]` Zhaorun Chen, Mintong Kang, Bo Li (2025). *ShieldAgent: Shielding Agents via Verifiable Safety Policy Reasoning*. (arXiv:2503.22738 (ICLR 2025 Workshop on Foundation Models in the Wild))  
  [https://arxiv.org/abs/2503.22738](https://arxiv.org/abs/2503.22738)
  Builds a guardrail agent that extracts verifiable rules from policy documents, structures them into action-based probabilistic rule circuits, and at inference time performs probabilistic logic verification of each proposed action; reports ~90\% rule recall on safety benchmarks while cutting API queries and latency.

- `[chiariello2024declare]` Francesco Chiariello, Valeria Fionda, Antonio Ielo, Francesco Ricca (2024). *Direct Encoding of Declare Constraints in ASP*. (PADL 2024 (distinguished paper); extended version in TPLP 2025; arXiv:2412.10152)  
  [https://arxiv.org/abs/2412.10152](https://arxiv.org/abs/2412.10152)
  Gives a direct ASP encoding of Declare (an LTLf-based declarative process modeling language) that bypasses automaton translation, and applies it to log generation, query checking, and conformance checking on business processes.

- `[claessen2000quickcheck]` Koen Claessen, John Hughes (2000). *QuickCheck: A Lightweight Tool for Random Testing of Haskell Programs*. (ICFP 2000 (ACM SIGPLAN International Conference on Functional Programming))  
  [https://dl.acm.org/doi/10.1145/351240.351266](https://dl.acm.org/doi/10.1145/351240.351266)
  Introduces property-based testing: programmers write executable universally-quantified properties as specifications, and the tool generates random inputs from typed generators to falsify them, with automatic shrinking of counterexamples. Founded a whole subfield with descendants in 40+ languages.

- `[cutler2024cedar]` Joseph W. Cutler, Craig Disselkoen, Aaron Eline, Shaobo He, Kyle Headley, Michael Hicks, Kesha Hietala, Eleftherios Ioannidis, John Kastner, Anwar Mamat, Darin McAdams, Matt McCutchen, Neha Rungta, Emina Torlak, Andrew Wells (2024). *Cedar: A New Language for Expressive, Fast, Safe, and Analyzable Authorization*. (OOPSLA 2024 / arXiv:2403.04651)  
  [https://arxiv.org/abs/2403.04651](https://arxiv.org/abs/2403.04651)
  Introduces Cedar, an authorization policy DSL designed to be analyzable. The language is intentionally not Turing-complete and has a sound-and-complete SMT encoding via a symbolic compiler, with key safety/security properties mechanized in Lean.

- `[debenedetti2024agentdojo]` Edoardo Debenedetti, Jie Zhang, Mislav Balunovic, Luca Beurer-Kellner, Marc Fischer, Florian Tramer (2024). *AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents*. (NeurIPS 2024 Datasets and Benchmarks (arXiv:2406.13352))  
  [https://arxiv.org/abs/2406.13352](https://arxiv.org/abs/2406.13352)
  97 realistic agentic tasks across email, banking, and travel environments paired with 629 security test cases. Crucially, success and security violations are checked by formal utility functions over post-execution environment state rather than by an LLM judge, so the evaluator cannot be co-attacked by the same prompt injection.

- `[disselkoen2024howcedar]` Craig Disselkoen, Aaron Eline, Shaobo He, Kyle Headley, Michael Hicks, Kesha Hietala, John Kastner, Anwar Mamat, Matt McCutchen, Neha Rungta, Bhakti Shah, Emina Torlak, Andrew Wells (2024). *How We Built Cedar: A Verification-Guided Approach*. (FSE 2024 Industry Track / arXiv:2407.01688)  
  [https://arxiv.org/abs/2407.01688](https://arxiv.org/abs/2407.01688)
  Describes Verification-Guided Development (VGD): write an executable formal model, prove properties on it in Lean, then use differential random testing and property-based testing to keep the production Rust implementation in sync with the model. The process found 25 bugs.

- `[fuchs2025policyastype]` Matthew D. Fuchs (2025). *Policy as Code, Policy as Type: Access Control through Dependent Typing*. (arXiv:2506.01446)  
  [https://arxiv.org/abs/2506.01446](https://arxiv.org/abs/2506.01446)
  Argues access-control policies are best expressed as types in a dependently typed language (Agda/Lean) so that policy violations are type errors and proof obligations come for free. Directly contrasts the approach with Rego's untyped, Datalog-like style.

- `[goldstein2024pbtpractice]` Harrison Goldstein, Joseph W. Cutler, Daniel Dickstein, Benjamin C. Pierce, Andrew Head (2024). *Property-Based Testing in Practice*. (ICSE 2024 (IEEE/ACM 46th International Conference on Software Engineering))  
  [https://dl.acm.org/doi/10.1145/3597503.3639581](https://dl.acm.org/doi/10.1145/3597503.3639581)
  An interview study of 30 industrial PBT users at Jane Street, characterizing the real frictions of writing generators, controlling distributions, and getting actionable feedback on coverage. Identifies open research opportunities for distribution-aware generation and effectiveness feedback.

- `[gupta2026prose2policy]` Vatsal Gupta, Darshan Sreenivasamurthy (2026). *Prose2Policy (P2P): A Practical LLM Pipeline for Translating Natural-Language Access Policies into Executable Rego*. (Apple Machine Learning Research / arXiv:2603.15799)  
  [https://arxiv.org/abs/2603.15799](https://arxiv.org/abs/2603.15799)
  End-to-end LLM pipeline (detection, component extraction, schema validation, lint, compile, auto-generated positive and negative tests) that turns natural-language access-control policies into Rego with 95.3\% compile rate and high test-pass rates on the ACRE dataset.

- `[he2025pgs]` Lehan He, Zeren Chen, Zhe Zhang, Xiang Gao, Lu Sheng (2025). *Use Property-Based Testing to Bridge LLM Code Generation and Validation*. (arXiv:2506.18315 (cs.SE))  
  [https://arxiv.org/abs/2506.18315](https://arxiv.org/abs/2506.18315)
  Proposes Property-Generated Solver (PGS): a Generator LLM and a Tester LLM iterate on code using property-based tests as the validation engine, where high-level invariants (not specific I/O pairs) drive feedback and refinement. Reports 23-37\% relative pass@1 gains over TDD baselines.

- `[horner2025legaldll]` Elias Horner, Cristinel Mateis, Guido Governatori, Agata Ciabattoni (2025). *Toward Robust Legal Text Formalization into Defeasible Deontic Logic using LLMs*. (arXiv:2506.08899)  
  [https://arxiv.org/abs/2506.08899](https://arxiv.org/abs/2506.08899)
  An LLM pipeline that segments natural-language regulation into atomic norms and emits Defeasible Deontic Logic rules, with a two-stage refinement loop and a new success metric. Evaluated on Australian telecommunications regulations against expert formalizations.

- `[karlsson2020quickrest]` Stefan Karlsson, Adnan Causevic, Daniel Sundmark (2020). *QuickREST: Property-based Test Generation of OpenAPI-Described RESTful APIs*. (ICST 2020 (IEEE International Conference on Software Testing, Verification and Validation); arXiv:1912.09686)  
  [https://arxiv.org/abs/1912.09686](https://arxiv.org/abs/1912.09686)
  Derives property-based tests and oracles automatically from a machine-readable OpenAPI specification, exposing mismatches between spec and implementation on industrial REST services with low engineering effort.

- `[lam2022defeasible]` Ho-Pun Lam, Mustafa Hashmi, Akhil Kumar (2022). *Automating Defeasible Reasoning in Law with Answer Set Programming*. (arXiv:2205.07335)  
  [https://arxiv.org/abs/2205.07335](https://arxiv.org/abs/2205.07335)
  Studies defeasible reasoning over legal norms and contracts using ASP, identifying rule modifiers that specify how rules override one another and providing transformations that eliminate these modifiers, yielding an ASP program whose stable models capture the intended legal conclusions.

- `[li2024formalllm]` Zelong Li, Wenyue Hua, Hao Wang, He Zhu, Yongfeng Zhang (2024). *Formal-LLM: Integrating Formal Language and Natural Language for Controllable LLM-based Agents*. (arXiv preprint (cs.LG))  
  [https://arxiv.org/abs/2402.00798](https://arxiv.org/abs/2402.00798)
  Encodes developer-specified planning constraints as a pushdown automaton that supervises an LLM's plan generation, ensuring every generated plan is accepted by the automaton; reports >50\% performance gains on benchmark and real-world tasks.

- `[lim2022defeasibleasp]` How Khang Lim, Avishkar Mahajar, Martin Strecker, Meng Weng Wong (2022). *Automating Defeasible Reasoning in Law with Answer Set Programming*. (ICLP 2022 Workshops (GDE 2022))  
  [https://ink.library.smu.edu.sg/cclaw/1/](https://ink.library.smu.edu.sg/cclaw/1/)
  Translates defeasible legal rules (with priorities and overrides) into Answer Set Programs, and contrasts ASP against SMT for executing the resulting policy logic. Implements semantics for the L4 legal DSL by elaborating rule modifiers into ASP meta-rules.

- `[lin2024clmasp]` Xinrui Lin, Yangfan Wu, Huanyu Yang, Yu Zhang, Yanyong Zhang, Jianmin Ji (2024). *CLMASP: Coupling Large Language Models with Answer Set Programming for Robotic Task Planning*. (arXiv preprint (cs.AI))  
  [https://arxiv.org/abs/2406.03367](https://arxiv.org/abs/2406.03367)
  LLM generates a skeleton plan; ASP refines it using formal action knowledge (preconditions/effects), raising executable-plan rate on VirtualHome from <2\% to >90\%.

- `[liu2023agentbench]` Xiao Liu, Hao Yu, Hanchen Zhang, Yifan Xu, Xuanyu Lei, Hanyu Lai, Yu Gu, Hangliang Ding, Kaiwen Men, Kejuan Yang, Shudan Zhang, Xiang Deng, Aohan Zeng, Zhengxiao Du, Chenhui Zhang, Sheng Shen, Tianjun Zhang, Yu Su, Huan Sun, Minlie Huang, Yuxiao Dong, Jie Tang (2023). *AgentBench: Evaluating LLMs as Agents*. (ICLR 2024 / arXiv:2308.03688)  
  [https://arxiv.org/abs/2308.03688](https://arxiv.org/abs/2308.03688)
  A multi-environment benchmark with 8 interactive settings (OS, DB, knowledge graph, card game, etc.) systematically evaluating 29 LLMs as agents, with per-environment success criteria.

- `[maaz2025agenticpbt]` Muhammad Maaz, Liam DeVoe, Zac Hatfield-Dodds, Nicholas Carlini (2025). *Agentic Property-Based Testing: Finding Bugs Across the Python Ecosystem*. (NeurIPS 2025 Deep Learning for Code Workshop; arXiv:2510.09907)  
  [https://arxiv.org/abs/2510.09907](https://arxiv.org/abs/2510.09907)
  An LLM agent infers function-specific and cross-function properties from code and docs, synthesizes Hypothesis property-based tests, executes them, and produces actionable bug reports; 56\% of generated reports were valid bugs across 100 popular Python packages, with patches merged into NumPy and other libraries.

- `[merigoux2021catala]` Denis Merigoux, Nicolas Chataing, Jonathan Protzenko (2021). *Catala: A Programming Language for the Law*. (Proc. ACM Program. Lang. (ICFP) 5)  
  [https://arxiv.org/abs/2103.03198](https://arxiv.org/abs/2103.03198)
  Designs a domain-specific language for translating statutory law (tax code, family benefits) into executable specifications using prioritized default logic, with a verified compiler and a methodology in which lawyers and programmers co-author rules line-by-line against the legislative source.

- `[mialon2023gaia]` Grégoire Mialon, Clémentine Fourrier, Craig Swift, Thomas Wolf, Yann LeCun, Thomas Scialom (2023). *GAIA: a benchmark for General AI Assistants*. (ICLR 2024 / arXiv:2311.12983)  
  [https://arxiv.org/abs/2311.12983](https://arxiv.org/abs/2311.12983)
  466 real-world questions requiring reasoning, multimodality, web browsing and tool use, hand-annotated with a single unambiguous string answer for exact-match scoring; humans reach 92\% vs. 15\% for GPT-4 with plugins.

- `[miculicich2025veriguard]` Lesly Miculicich, Mihir Parmar, Hamid Palangi, Krishnamurthy Dj Dvijotham, Mirko Montanari, Tomas Pfister, Long T. Le (2025). *VeriGuard: Enhancing LLM Agent Safety via Verified Code Generation*. (arXiv preprint (cs.SE), Google Research)  
  [https://arxiv.org/abs/2510.05156](https://arxiv.org/abs/2510.05156)
  Two-stage architecture: an offline stage synthesizes a behavioral policy from user intent and formally verifies it against safety specifications, then an online stage uses the verified policy as a runtime monitor for each proposed agent action.

- `[morris2023blawx]` Jason Morris (2023). *Blawx: User-friendly Goal-Directed Answer Set Programming for Rules as Code*. (ProLaLa 2023 workshop @ POPL; CEUR-WS Vol-3193)  
  [https://ceur-ws.org/Vol-3193/paper4GDE.pdf](https://ceur-ws.org/Vol-3193/paper4GDE.pdf)
  Presents Blawx, a web-based Blockly front-end over s(CASP) for non-programmers to encode, simulate, test, and explain legal rules; deployed for Canadian privacy and policy reasoning.

- `[nakash2025taubreak]` Itay Nakash, George Kour, Koren Lazar, Matan Vetzler, Guy Uziel, Ateret Anaby-Tavor (2025). *Effective Red-Teaming of Policy-Adherent Agents*. (arXiv:2506.09600 (cs.MA))  
  [https://arxiv.org/abs/2506.09600](https://arxiv.org/abs/2506.09600)
  Introduces tau-break, an adversarial extension of tau-bench's airline/retail domains, and CRAFT, a multi-agent red-team system that uses policy-aware persuasive strategies (rather than DAN-style jailbreaks) to coerce policy-adherent customer-service agents into granting prohibited refunds, exchanges, or exceptions. Shows that simple defenses are insufficient.

- `[qin2023toolllm]` Yujia Qin, Shihao Liang, Yining Ye, Kunlun Zhu, Lan Yan, Yaxi Lu, Yankai Lin, Xin Cong, Xiangru Tang, Bill Qian, Sihan Zhao, Lauren Hong, Runchu Tian, Ruobing Xie, Jie Zhou, Mark Gerstein, Dahai Li, Zhiyuan Liu, Maosong Sun (2023). *ToolLLM: Facilitating Large Language Models to Master 16000+ Real-world APIs*. (ICLR 2024 / arXiv:2307.16789)  
  [https://arxiv.org/abs/2307.16789](https://arxiv.org/abs/2307.16789)
  Introduces ToolBench, a tool-use dataset spanning 3,451 tools and 16,464 real-world RapidAPI endpoints, with an automated ToolEval evaluator (LLM-judge based) used to fine-tune ToolLLaMA.

- `[ramli2012xacml]` Carroline Dewi Puspa Kencana Ramli, Hanne Riis Nielson, Flemming Nielson (2012). *XACML 3.0 in Answer Set Programming*. (LOPSTR 2012; LNCS 7844, Springer 2013; arXiv:1206.5327)  
  [https://arxiv.org/abs/1206.5327](https://arxiv.org/abs/1206.5327)
  Gives a systematic translation of XACML 3.0 access-control policies into ASP such that the unique answer set matches XACML's standard semantics, enabling off-the-shelf ASP solvers to verify completeness, redundancy, conflicts, refinement, reachability, and usefulness of policy sets.

- `[su2026nsvif]` Yiming Su, Kunzhao Xu, Yanjie Gao, Fan Yang, Cheng Li, Mao Yang, Tianyin Xu (2026). *Neuro-Symbolic Verification on Instruction Following of LLMs*. (arXiv preprint (cs.AI))  
  [https://arxiv.org/abs/2601.17789](https://arxiv.org/abs/2601.17789)
  Formalizes instruction-following verification as a constraint-satisfaction problem; LLMs translate instructions into first-order-logic predicates and a Z3-based unified solver checks compliance. Introduces VIFBENCH with fine-grained labels.

- `[wang2025agentspec]` Haoyu Wang, Christopher M. Poskitt, Jun Sun (2025). *AgentSpec: Customizable Runtime Enforcement for Safe and Reliable LLM Agents*. (ICSE 2026 (preprint arXiv:2503.18666))  
  [https://arxiv.org/abs/2503.18666](https://arxiv.org/abs/2503.18666)
  A lightweight domain-specific language for specifying runtime constraints on LLM agents via triggers, predicates, and enforcement actions, achieving >90\% prevention of unsafe code-agent executions with millisecond overhead.

- `[winston2026solveraided]` Cailin Winston, Claris Winston, René Just (2026). *Solver-Aided Verification of Policy Compliance in Tool-Augmented LLM Agents*. (arXiv preprint (cs.SE))  
  [https://arxiv.org/abs/2603.20449](https://arxiv.org/abs/2603.20449)
  Translates natural-language tool-use policies into SMT-LIB-2.0 constraints and intercepts planned tool calls at runtime, using Z3 to check each call against the policy before execution. Evaluated on tau-bench, reducing policy violations while preserving task accuracy.

- `[xie2024osworld]` Tianbao Xie, Danyang Zhang, Jixuan Chen, Xiaochuan Li, Siheng Zhao, Ruisheng Cao, Toh Jing Hua, Zhoujun Cheng, Dongchan Shin, Fangyu Lei, Yitao Liu, Yiheng Xu, Shuyan Zhou, Silvio Savarese, Caiming Xiong, Victor Zhong, Tao Yu (2024). *OSWorld: Benchmarking Multimodal Agents for Open-Ended Tasks in Real Computer Environments*. (NeurIPS 2024 D&B / arXiv:2404.07972)  
  [https://arxiv.org/abs/2404.07972](https://arxiv.org/abs/2404.07972)
  369 real computer-use tasks across Ubuntu, Windows and macOS with per-task initial-state setup scripts and execution-based evaluation scripts; humans 72.4\% vs. best model 12.2\%.

- `[yao2024taubench]` Shunyu Yao, Noah Shinn, Pedram Razavi, Karthik Narasimhan (2024). *τ-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains*. (ICLR 2025 / arXiv:2406.12045)  
  [https://arxiv.org/abs/2406.12045](https://arxiv.org/abs/2406.12045)
  Introduces τ-bench, a benchmark of two customer-service domains (retail, airline) in which an LLM agent interacts with a simulated user and a programmatic API under a natural-language policy document. Success is judged by deterministic comparison of the final database state to an annotated goal state, and reliability across trials is measured with a new pass^k metric.

- `[ye2023satlm]` Xi Ye, Qiaochu Chen, Isil Dillig, Greg Durrett (2023). *SatLM: Satisfiability-Aided Language Models Using Declarative Prompting*. (NeurIPS 2023)  
  [https://arxiv.org/abs/2305.09656](https://arxiv.org/abs/2305.09656)
  Prompts the LLM to emit a declarative specification of the problem rather than an imperative solution, then derives the answer with an off-the-shelf theorem prover; achieves state-of-the-art on LSAT and BoardgameQA and +23\% on GSM.

- `[zeng2026logigen]` Yucheng Zeng, et al. (2026). *LOGIGEN: Logic-Driven Generation of Verifiable Agentic Tasks*. (arXiv:2603.00540)  
  [https://arxiv.org/abs/2603.00540](https://arxiv.org/abs/2603.00540)
  Proposes a logic-driven pipeline that compiles natural-language policy into database constraints, initializes boundary states near policy conflicts, and verifies trajectories by exact state equivalence; uses the resulting 20k tasks across 8 domains for SFT+RL training and reports large gains on τ²-Bench.

- `[zhan2024injecagent]` Qiusi Zhan, Zhixiang Liang, Zifan Ying, Daniel Kang (2024). *InjecAgent: Benchmarking Indirect Prompt Injections in Tool-Integrated Large Language Model Agents*. (Findings of ACL 2024 (arXiv:2403.02691))  
  [https://arxiv.org/abs/2403.02691](https://arxiv.org/abs/2403.02691)
  1,054 test cases over 17 user tools and 62 attacker tools, categorizing attack intents into direct user harm and private-data exfiltration. Shows ReAct-prompted GPT-4 is fooled ~24\% of the time, roughly doubling under a hacking-prompt enhancement.

- `[zhang2024agentsafetybench]` Zhexin Zhang, Shiyao Cui, Yida Lu, Jingzhuo Zhou, Junxiao Yang, Hongning Wang, Minlie Huang (2024). *Agent-SafetyBench: Evaluating the Safety of LLM Agents*. (arXiv:2412.14470 (cs.CL))  
  [https://arxiv.org/abs/2412.14470](https://arxiv.org/abs/2412.14470)
  349 interaction environments and 2,000 test cases spanning 8 safety-risk categories and 10 common failure modes. Across 16 popular agents, none scores above 60\% on safety, and the authors isolate two root causes: lack of robustness and lack of risk awareness.

- `[zhang2025asb]` Hanrong Zhang, Jingyuan Huang, Kai Mei, Yifei Yao, Zhenting Wang, Chenlu Zhan, Hongwei Wang, Yongfeng Zhang (2025). *AgentHarm and friends notwithstanding: Agent Security Bench (ASB) -- Formalizing and Benchmarking Attacks and Defenses in LLM-based Agents*. (ICLR 2025 (arXiv:2410.02644))  
  [https://arxiv.org/abs/2410.02644](https://arxiv.org/abs/2410.02644)
  Unified benchmark that formalizes 10 attack vectors against LLM agents -- including direct prompt injection, indirect prompt injection, memory poisoning, plan-of-thought backdoors, and mixed attacks -- across 10 scenarios and 400 tools, with both attack-success-rate and refusal-rate metrics.

- `[zhou2023webarena]` Shuyan Zhou, Frank F. Xu, Hao Zhu, Xuhui Zhou, Robert Lo, Abishek Sridhar, Xianyi Cheng, Tianyue Ou, Yonatan Bisk, Daniel Fried, Uri Alon, Graham Neubig (2023). *WebArena: A Realistic Web Environment for Building Autonomous Agents*. (ICLR 2024 / arXiv:2307.13854)  
  [https://arxiv.org/abs/2307.13854](https://arxiv.org/abs/2307.13854)
  Provides a reproducible, fully self-hosted web environment over four real applications (e-commerce, forum, GitLab, CMS) with 812 long-horizon tasks evaluated via execution-based functional correctness checks defined per task.
