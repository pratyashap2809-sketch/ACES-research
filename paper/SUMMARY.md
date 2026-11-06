# Paper summary — "What Is Your AI Agent Buying?"

**Authors:** Amine Allouah, Omar Besbes, Josué D. Figueroa, Yash Kanoria, Akshit Kumar
**arXiv:** [2508.02630v2](https://arxiv.org/abs/2508.02630) (version of 13 Oct 2025)
**Original code:** https://github.com/mycustomai/ACES
**PDF:** [`ACES_paper_2508.02630v2.pdf`](ACES_paper_2508.02630v2.pdf)

## Research question
When AI agents shop on behalf of consumers, *what do they buy, and why?*

## The system: ACES (Agentic e-CommercE Simulator)
- A provider-agnostic **vision-language-model (VLM) shopping agent** (LangChain + Selenium).
- A fully programmable **mock e-commerce storefront** showing 8 products in a 2 × 4 grid.
- Each episode: open the store → screenshot the grid → ask the model with a generic prompt → record which product it adds to cart.
- 8 categories: fitness watch, iPhone 16 Pro cover, mousepad, office lamp, stapler, toilet paper, toothpaste, washing machine (8 real Amazon listings each).
- Also tested in a **headless/API mode** (ranked JSON list, no images).

## Three experiments
| Name | What it tests | Design |
|---|---|---|
| **ACE-RS** | Instruction following & basic rationality | Budget / colour / brand tasks; choice sets where one item is strictly cheaper or better-rated |
| **ACE-BB** | Biases & attribute sensitivities | 500 randomized scenarios per category (positions, tags, price, rating, reviews), fitted with a conditional logit model |
| **ACE-SR** | Seller response | A seller-side AI rewrites one product's description; rerun 200 trials and measure market-share change |

Models: Claude Sonnet 4, GPT-4.1, Gemini 2.5 Flash (plus older models in the rationality tests).

## Key findings
1. **Rationality:** newer models follow instructions almost perfectly, but still miss small advantages (e.g. a +0.1 rating bump fooled Claude Sonnet 4 in 28.7% of trials, GPT-4.1 in 15.1%).
2. **Market shares differ by model and can concentrate** on a few products; some brands are never chosen.
3. **Position bias is large and model-specific:** all models favour the top row, but GPT-4.1 prefers column 1, Claude Sonnet 4 the middle columns, Gemini 2.5 Flash columns 3–4. There is no universal "top" slot.
4. **Tags:** "Sponsored" lowers selection; "Overall Pick" raises it a lot (10% baseline → ~20–43%); scarcity tags matter little.
5. **Attributes:** all models prefer lower price, higher rating, more reviews — price elasticities ≈ −1.6 to −2.2, similar to human shoppers — but magnitudes vary across models.
6. **Seller agents:** a single AI rewrite of a product description raised average market share by +2.7 to +5.6 percentage points, and by up to +23.6 p.p. in some category–model pairs.
7. **Robustness:** position and badge effects persist in the headless JSON interface and when the prompt says "ignore position". A "prioritize price" prompt does make agents more price-sensitive.

## Implications
- **Platforms:** ranking/layout must account for agent-specific position bias; classic ad levers may weaken.
- **Sellers:** listings need continual re-optimization as models change.
- **Consumers:** should state preferences (e.g. price sensitivity) explicitly to their agent.
- **Evaluation:** proposes public "choice profile" dashboards for shopping agents rather than leaderboards.

## Possible directions for the 12-week project
- Replicate ACE-BB on one category with a newer model and compare coefficients to Table 1.
- Test iterative (multi-round) seller optimization, or several competing seller agents.
- Add a product-detail page / deeper navigation to see if position bias shrinks.
- Compare agent choices with a small human survey on the same grid.
