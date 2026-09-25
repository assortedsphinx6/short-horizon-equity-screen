# Project: Quant Research

**The Objective:** Deeter Analytics is a proprietary investment firm. The PM trades a short horizon long/short book on market psychology and flow, and has a long list of hunches he would like to see run as screens and alerts. The quant seat exists to turn those into things that run, working with a small tech team. We want to see what you do with a message like the two below: the definitions you choose, what you build in an afternoon, and how honest you are about what the evidence does and does not show.

**The Mandate:** Both messages below are fictitious, but they are the shape of the job. Budget four hours. Use free, public data only. We will run your code, so send a Git repo (a zip is acceptable) with a README. Most of this is deliberately underspecified; the PM's words are fuzzy on purpose, and deciding what they mean is the work. Use AI however you like, but add one line at the end saying how you used it. We assess reasoning, correctness, reproducibility, and communication, not backtest profitability.

**The Messages:**

> *PM, 6:58 AM: Want to make this systematic. Every week there are a few names everyone is excited about with volume, but then there are a few consolidation days. From there, either it goes again Friday, or it stalls. I want a list Thursday night of names like this, with your read on which way each one is leaning and why, so I can look at them Friday morning.*
>
> *PM, 11:18 AM: also would love an alert if I'm doing well quickly on many positions*

**Your Deliverable Must Include:**

1. **The Definitions.** Turn the PM's words into rules a machine can run: what counts as "everyone is excited about," "with volume," "a few consolidation days," "goes again" versus "stalls," and "leaning." Every threshold gets a number and one line on why that number. Where his words could mean two different things, say so.
2. **The Screen.** Working code, any language, free public data only, that produces the Thursday night list as of the latest close: ticker, the numbers behind each rule, the lean, one line of reason.
3. **The Evidence.** Whatever check four hours allow. At minimum, run your rules back over recent weeks and report what happened on Fridays, with the sample size and the obvious traps named: look-ahead, survivorship, thresholds fitted to the answer. Be explicit about what free data cannot test and how you would test it with the right data.
4. **The Note to the PM.** Eight lines he can read before the open: what the screen does, the names and leans it produced, what it does not know, and the one thing you would want to test next. No p-values.
5. **The Note to the PM.** The second message, half a page, no code: what "doing well," "quickly" and "many positions" should default to, how often it may fire, and how you would stop it crying wolf.
