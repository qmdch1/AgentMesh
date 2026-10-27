# AgentMesh contribution rules

- Keep this app a static, dependency-free runtime. Node is only needed for the local server and development checks.
- Keep user-facing labels and instructions in Korean. Maintain simulation wording; do not present scripted events as live model traffic or measured metrics.
- Define node roles and scenarios in `src/flows.js`; preserve continuous routes and a final verification before returning to OMP.
- Preserve keyboard controls, reduced-motion behavior and mobile map scrolling when changing the interface.
- Run `npm test` and `npm run test:browser` for flow or interaction changes. Use `npx playwright install chromium` if the test browser is missing.
- Never include API keys or credentials in this static frontend.
