# Model and pricing verification (2026-10-25)

Read by the development agent from OpenAI's official documentation on 2026-10-25 (no date is printed on the pages themselves):

| Item | Value | Source |
|---|---|---|
| API model id | `gpt-5.6-luna` exists as an API model id (not only a ChatGPT label) | https://developers.openai.com/api/docs/models/gpt-5.6-luna |
| Standard-tier price | **US$0.20 / 1M input tokens, US$1.20 / 1M output tokens** | same page and https://developers.openai.com/api/docs/pricing |
| Long-context surcharge | prompts over 272K input tokens cost 2x input and 1.5x output; not applicable here (inputs are a few thousand tokens), multiplier used: 1 | model page |
| Context / output | 1,050,000 context, 128,000 max output | model page |
| Interface | Responses API (`v1/responses`) and Structured Outputs listed as supported, which is what `OpenAIReasoningProvider` uses | model page |
| Reasoning | reasoning tokens are billed as output; `max_output_tokens` bounds them (the ledger reserves the full `max_output_tokens` per call) | provider code and model docs |

Notes and caveats
- The models overview page does not list `gpt-5.6-luna` (it shows a newer generation), while the pricing page and the model page do. The model page is treated as authoritative.
- A newer, cheaper sibling, `gpt-6-luna` (US$0.10 / US$0.50 per 1M), is also documented. It was **not** substituted: the owner approved `gpt-5.6-luna`, which is Serapis's configured default (`DEFAULT_OPENAI_MODEL`).
- Cached-input discounts are ignored by the ledger (over-reserves); no tools or web search are used, so no tool fees apply.
- The API does not report billed cost; cost figures in the results are tokens x these rates.
- This is an agent reading of public documentation, not an invoice. The provider-side usage page is the real backstop.
