# LaTeX review checklist

- [x] English reviewed draft is the source for the generated body.
- [x] Main comparison keeps B0, B1, B2, F0, and F1.
- [x] Deprecated experiment-group names do not appear in the LaTeX workspace.
- [x] Main metrics and CFR values match the audited paper database.
- [x] F0/F1 uses a shared hybrid RRF top-50 pool; observed CFR equality is reported as an observation, not an invariant.
- [x] QA provider difference (F1 Alibaba Cloud DashScope; historical runs Moonshot) is disclosed.
- [x] Appendix covers prompts, algorithms, complexity, qrels/CFR, protocol, audit slices, cost, and reproducibility.
- [x] Static environment check passes: balanced delimiters, environments, citations, and figure files.
- [ ] Run the built-in LaTeX compiler when its standard directories are available.
- [ ] Replace `Anonymous Authors` and confirm the final title/author block.
- [ ] Review figure placement and table page breaks in the compiled PDF.
- [ ] Add the final arXiv metadata and license statement if required.
