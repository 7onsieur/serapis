"""Stage 3 second holdout (business-school calculations). Expected outcomes were fixed BEFORE this set was run against
any verifier change, and are not edited afterwards. Disjoint from adversarial_stage3.py and holdout_stage3.py.

  ACCEPT  correct, grounded, may be shown.      BLOCK  must not be shown (wrong, ungrounded, unverifiable or unspecified).
"""

from __future__ import annotations

from holdout_stage3 import inp, spec, step

P_GM = "Gross profit is revenue minus cost of goods sold. Gross margin is gross profit divided by revenue."
P_BE = ("Contribution margin per unit is the price minus the variable cost per unit. Break-even quantity is fixed costs "
        "divided by contribution margin per unit.")
P_ROI = "Return on investment is the net profit divided by the cost of the investment."
P_PCT = "The change is the new value minus the original value. The percentage change is the change divided by the original value."
P_INC = "Income elasticity of demand is the percentage change in quantity demanded divided by the percentage change in income."
P_PRICEEL = "Price elasticity of demand is the percentage change in quantity demanded divided by the percentage change in price."
P_CR = "The current ratio is current assets divided by current liabilities. A current ratio of about 2 is conventionally considered healthy."
P_DE = "The debt-to-equity ratio is total debt divided by total equity."
P_INV = "Inventory turnover is cost of goods sold divided by average inventory."
P_EPS = "Earnings per share is net income divided by the number of shares."
P_PE = "The price-earnings ratio is the share price divided by earnings per share."
P_MARKUP = "The selling price is the cost multiplied by one plus the markup."
P_PM = "Profit is revenue minus cost. Profit margin is profit divided by revenue."
P_NET = "The net result is the gain minus the loss."
P_PAY = "The payback period is the investment divided by the annual cash flow."
P_TAX = "Net profit is profit multiplied by one minus the tax rate."
P_GP_EXAMPLE = P_GM + " For example, a small shop might report a gross profit of 280 in a good month."

Q_GM = "A firm has revenue of 800 and cost of goods sold of 520. What is its gross margin?"
Q_PCT_UP = "Sales rise from 40 to 50. What is the percentage change?"
GM_IN = [inp("rev", "revenue", "800"), inp("cogs", "cost of goods sold", "520")]
CR_Q = "A firm has current assets of 900 and current liabilities of 600. What is the current ratio?"
BE_Q = "Fixed costs are 12000, the price is 50 per unit and the variable cost is 30 per unit. What is the break-even quantity?"
BE_IN = [inp("fc", "fixed costs", "12000"), inp("p", "price", "50"), inp("vc", "variable cost per unit", "30")]
ROI_Q = "An investment of 60000 earns a net profit of 15000. What is the return on investment?"
PCT_IN = [inp("o", "original value", "40"), inp("n", "new value", "50")]

# (id, category, question, expected answer, passage, spec or None, expected outcome)
CASES = [
    ("v_gross_margin", "valid", Q_GM, "Gross profit is 280, so gross margin is 280 divided by 800, which is 35%.", P_GM,
     spec(GM_IN, [step("gp", "gross profit", "rev - cogs"), step("gm", "gross margin", "gp / rev")], "35", "%"), "ACCEPT"),
    ("v_break_even", "valid", BE_Q,
     "Contribution margin per unit is 50 minus 30, which is 20, so break-even quantity is 12000 divided by 20, which is 600.", P_BE,
     spec(BE_IN, [step("cm", "contribution margin per unit", "p - vc"), step("be", "break-even quantity", "fc / cm")], "600"),
     "ACCEPT"),
    ("v_roi", "valid", ROI_Q, "Return on investment is 15000 divided by 60000, which is 25%.", P_ROI,
     spec([inp("np", "net profit", "15000"), inp("ci", "cost of the investment", "60000")],
          [step("roi", "return on investment", "np / ci")], "25", "%"), "ACCEPT"),
    ("v_roi_rounded", "valid", "An investment of 30000 earns a net profit of 7000. What is the return on investment?",
     "Return on investment is 7000 divided by 30000, which is 23.33% to two places.", P_ROI,
     spec([inp("np", "net profit", "7000"), inp("ci", "cost of the investment", "30000")],
          [step("roi", "return on investment", "np / ci")], "23.33", "%", 2), "ACCEPT"),
    ("v_pct_change_up", "valid", Q_PCT_UP, "The change is 10, so the percentage change is 10 divided by 40, which is 25%.", P_PCT,
     spec(PCT_IN, [step("c", "change", "n - o"), step("pc", "percentage change", "c / o")], "25", "%"), "ACCEPT"),
    ("v_pct_change_down", "valid", "Sales fall from 50 to 40. What is the percentage change?",
     "The change is negative 10, so the percentage change is negative 10 divided by 50, which is negative 20%.", P_PCT,
     spec([inp("o", "original value", "50"), inp("n", "new value", "40")],
          [step("c", "change", "n - o"), step("pc", "percentage change", "c / o")], "-20", "%"), "ACCEPT"),
    ("v_income_elasticity", "valid", "Income rises by 10% and quantity demanded rises by 15%. What is the income elasticity of demand?",
     "It is 15 divided by 10, which is 1.5.", P_INC,
     spec([inp("dq", "percentage change in quantity demanded", "15", "%"), inp("di", "percentage change in income", "10", "%")],
          [step("e", "income elasticity of demand", "dq / di")], "1.5"), "ACCEPT"),
    ("v_price_elasticity_negative", "valid", "Price rises by 10% and quantity demanded falls by 15%. What is the price elasticity of demand?",
     "It is negative 15 divided by 10, which is negative 1.5.", P_PRICEEL,
     spec([inp("dq", "percentage change in quantity demanded", "-15", "%"), inp("dp", "percentage change in price", "10", "%")],
          [step("e", "price elasticity of demand", "dq / dp")], "-1.5"), "ACCEPT"),
    ("v_current_ratio", "valid", CR_Q, "The current ratio is 900 divided by 600, which is 1.5.", P_CR,
     spec([inp("ca", "current assets", "900"), inp("cl", "current liabilities", "600")],
          [step("cr", "current ratio", "ca / cl")], "1.5"), "ACCEPT"),
    ("v_debt_to_equity", "valid", "A firm has total debt of 450 and total equity of 900. What is the debt-to-equity ratio?",
     "The debt-to-equity ratio is 450 divided by 900, which is 0.5.", P_DE,
     spec([inp("d", "total debt", "450"), inp("e", "total equity", "900")], [step("r", "debt-to-equity ratio", "d / e")], "0.5"),
     "ACCEPT"),
    ("v_inventory_turnover", "valid", "A firm has cost of goods sold of 2400 and an average inventory of 600. What is the inventory turnover?",
     "Inventory turnover is 2400 divided by 600, which is 4.", P_INV,
     spec([inp("c", "cost of goods sold", "2400"), inp("i", "average inventory", "600")],
          [step("t", "inventory turnover", "c / i")], "4"), "ACCEPT"),
    ("v_eps_rounded", "valid", "A firm has net income of 1000 and 300 shares. What is the earnings per share?",
     "Earnings per share is 1000 divided by 300, which is 3.33 to two places.", P_EPS,
     spec([inp("ni", "net income", "1000"), inp("s", "number of shares", "300")],
          [step("eps", "earnings per share", "ni / s")], "3.33", "", 2), "ACCEPT"),
    ("v_pe_ratio", "valid", "A share price is 45 and earnings per share is 3. What is the price-earnings ratio?",
     "The price-earnings ratio is 45 divided by 3, which is 15.", P_PE,
     spec([inp("p", "share price", "45"), inp("e", "earnings per share", "3")], [step("pe", "price-earnings ratio", "p / e")], "15"),
     "ACCEPT"),
    ("v_markup", "valid", "A product costs 80 and the markup is 25%. What is the selling price?",
     "The selling price is 80 multiplied by one plus 25%, which is 100.", P_MARKUP,
     spec([inp("c", "cost", "80"), inp("m", "markup", "25", "%")], [step("sp", "selling price", "c * (1 + m)")], "100"), "ACCEPT"),
    ("v_negative_margin", "valid", "A shop has revenue of 300 and cost of 360. What is the profit margin?",
     "Profit is negative 60, so the profit margin is negative 60 divided by 300, which is negative 20%.", P_PM,
     spec([inp("r", "revenue", "300"), inp("c", "cost", "360")],
          [step("p", "profit", "r - c"), step("pm", "profit margin", "p / r")], "-20", "%"), "ACCEPT"),
    ("v_loss_as_magnitude", "valid", "A firm has a gain of 200 and a loss of 50. What is the net result?",
     "The net result is 200 minus 50, which is 150.", P_NET,
     spec([inp("g", "gain", "200"), inp("l", "loss", "50")], [step("n", "net result", "g - l")], "150"), "ACCEPT"),
    ("v_payback", "valid", "An investment of 60000 returns an annual cash flow of 15000. What is the payback period?",
     "The payback period is 60000 divided by 15000, which is 4 years.", P_PAY,
     spec([inp("i", "investment", "60000"), inp("cf", "annual cash flow", "15000")], [step("pb", "payback period", "i / cf")], "4"),
     "ACCEPT"),
    # wrong formula / arithmetic / assignment
    ("w_gm_wrong_denominator", "wrong", Q_GM, "Gross profit is 280, so gross margin is 280 divided by 520, which is 53.85%.", P_GM,
     spec(GM_IN, [step("gp", "gross profit", "rev - cogs"), step("gm", "gross margin", "gp / cogs")], "53.85", "%", 2), "BLOCK"),
    ("w_break_even_price_not_margin", "wrong", BE_Q, "Break-even quantity is 12000 divided by 50, which is 240.", P_BE,
     spec(BE_IN, [step("be", "break-even quantity", "fc / p")], "240"), "BLOCK"),
    ("w_roi_inverted", "wrong", ROI_Q, "Return on investment is 60000 divided by 15000, which is 4.", P_ROI,
     spec([inp("np", "net profit", "15000"), inp("ci", "cost of the investment", "60000")],
          [step("roi", "return on investment", "ci / np")], "4"), "BLOCK"),
    ("w_pct_change_new_denominator", "wrong", Q_PCT_UP, "The change is 10, so the percentage change is 10 divided by 50, which is 20%.", P_PCT,
     spec(PCT_IN, [step("c", "change", "n - o"), step("pc", "percentage change", "c / n")], "20", "%"), "BLOCK"),
    ("w_elasticity_inverted", "wrong", "Income rises by 10% and quantity demanded rises by 15%. What is the income elasticity of demand?",
     "It is 10 divided by 15, which is 0.67 to two places.", P_INC,
     spec([inp("dq", "percentage change in quantity demanded", "15", "%"), inp("di", "percentage change in income", "10", "%")],
          [step("e", "income elasticity of demand", "di / dq")], "0.67", "", 2), "BLOCK"),
    ("w_current_ratio_inverted", "wrong", CR_Q, "The current ratio is 600 divided by 900, which is 0.67 to two places.", P_CR,
     spec([inp("ca", "current assets", "900"), inp("cl", "current liabilities", "600")],
          [step("cr", "current ratio", "cl / ca")], "0.67", "", 2), "BLOCK"),
    ("w_debt_equity_ungrounded_formula", "wrong", "A firm has total debt of 450 and total equity of 900. What is the debt-to-equity ratio?",
     "The ratio is 450 divided by 1350, which is 0.33 to two places.", P_DE,
     spec([inp("d", "total debt", "450"), inp("e", "total equity", "900")], [step("r", "debt-to-equity ratio", "d / (d + e)")],
          "0.33", "", 2), "BLOCK"),
    ("w_pe_multiplied", "wrong", "A share price is 45 and earnings per share is 3. What is the price-earnings ratio?",
     "The price-earnings ratio is 45 multiplied by 3, which is 135.", P_PE,
     spec([inp("p", "share price", "45"), inp("e", "earnings per share", "3")], [step("pe", "price-earnings ratio", "p * e")], "135"),
     "BLOCK"),
    ("w_markup_subtracted", "wrong", "A product costs 80 and the markup is 25%. What is the selling price?",
     "The selling price is 80 multiplied by one minus 25%, which is 60.", P_MARKUP,
     spec([inp("c", "cost", "80"), inp("m", "markup", "25", "%")], [step("sp", "selling price", "c * (1 - m)")], "60"), "BLOCK"),
    ("w_markup_percent_plain", "wrong", "A product costs 80 and the markup is 25%. What is the selling price?",
     "The selling price is 80 multiplied by one plus 25, which is 2080.", P_MARKUP,
     spec([inp("c", "cost", "80"), inp("m", "markup", "25")], [step("sp", "selling price", "c * (1 + m)")], "2080"), "BLOCK"),
    ("w_roi_arithmetic", "wrong", ROI_Q, "Return on investment is 15000 divided by 60000, which is 20%.", P_ROI,
     spec([inp("np", "net profit", "15000"), inp("ci", "cost of the investment", "60000")],
          [step("roi", "return on investment", "np / ci")], "20", "%"), "BLOCK"),
    ("w_break_even_arithmetic", "wrong", BE_Q,
     "Contribution margin per unit is 20, so break-even quantity is 12000 divided by 20, which is 500.", P_BE,
     spec(BE_IN, [step("cm", "contribution margin per unit", "p - vc"), step("be", "break-even quantity", "fc / cm")], "500"),
     "BLOCK"),
    ("w_eps_rounding", "wrong", "A firm has net income of 1000 and 300 shares. What is the earnings per share?",
     "Earnings per share is 1000 divided by 300, which is 3.34 to two places.", P_EPS,
     spec([inp("ni", "net income", "1000"), inp("s", "number of shares", "300")],
          [step("eps", "earnings per share", "ni / s")], "3.34", "", 2), "BLOCK"),
    ("w_swapped_preceding", "wrong", CR_Q, "The current ratio is 600 divided by 900, which is 0.67 to two places.", P_CR,
     spec([inp("ca", "current assets", "600"), inp("cl", "current liabilities", "900")],
          [step("cr", "current ratio", "ca / cl")], "0.67", "", 2), "BLOCK"),
    ("w_swapped_number_first", "wrong", "The figures are 900 for total equity and 450 for total debt. What is the debt-to-equity ratio?",
     "The debt-to-equity ratio is 900 divided by 450, which is 2.", P_DE,
     spec([inp("d", "total debt", "900"), inp("e", "total equity", "450")], [step("r", "debt-to-equity ratio", "d / e")], "2"),
     "BLOCK"),
    ("w_from_to_reversed", "wrong", "Sales fall from 50 to 40. What is the percentage change?",
     "The change is 10, so the percentage change is 10 divided by 40, which is 25%.", P_PCT,
     spec([inp("o", "original value", "40"), inp("n", "new value", "50")],
          [step("c", "change", "n - o"), step("pc", "percentage change", "c / o")], "25", "%"), "BLOCK"),
    ("w_fall_recorded_positive", "wrong", "Price falls by 10% and quantity demanded rises by 15%. What is the price elasticity of demand?",
     "It is 15 divided by 10, which is 1.5.", P_PRICEEL,
     spec([inp("dq", "percentage change in quantity demanded", "15", "%"), inp("dp", "percentage change in price", "10", "%")],
          [step("e", "price elasticity of demand", "dq / dp")], "1.5"), "BLOCK"),
    ("w_loss_recorded_negative", "wrong", "A firm has a gain of 200 and a loss of 50. What is the net result?",
     "The net result is 200 minus negative 50, which is 250.", P_NET,
     spec([inp("g", "gain", "200"), inp("l", "loss", "-50")], [step("n", "net result", "g - l")], "250"), "BLOCK"),
    ("w_hidden_tax_constant", "wrong", "A firm has profit of 1000 and a tax rate of 30%. What is the net profit?",
     "Net profit is 1000 multiplied by 0.7, which is 700.", P_TAX,
     spec([inp("p", "profit", "1000")], [step("np", "net profit", "p * (1 - 0.3)")], "700"), "BLOCK"),
    ("w_formula_not_in_passage", "wrong", "A firm has current assets of 900, inventory of 300 and current liabilities of 600. What is the quick ratio?",
     "The quick ratio is 900 minus 300 divided by 600, which is 1.", P_CR,
     spec([inp("ca", "current assets", "900"), inp("i", "inventory", "300"), inp("cl", "current liabilities", "600")],
          [step("q", "quick ratio", "(ca - i) / cl")], "1"), "BLOCK"),
    ("w_asks_margin_answers_profit", "wrong", Q_GM, "Gross profit is 800 minus 520, which is 280.", P_GM,
     spec(GM_IN, [step("gp", "gross profit", "rev - cogs")], "280"), "BLOCK"),
    ("w_extra_unsupported_number", "wrong", ROI_Q, "Return on investment is 15000 divided by 60000, which is 25%, against an industry average of 12%.", P_ROI,
     spec([inp("np", "net profit", "15000"), inp("ci", "cost of the investment", "60000")],
          [step("roi", "return on investment", "np / ci")], "25", "%"), "BLOCK"),
    ("w_extra_unsupported_claim", "wrong", ROI_Q, "Return on investment is 15000 divided by 60000, which is 25%, so the project will certainly beat its competitors.", P_ROI,
     spec([inp("np", "net profit", "15000"), inp("ci", "cost of the investment", "60000")],
          [step("roi", "return on investment", "np / ci")], "25", "%"), "BLOCK"),
    ("w_extra_unsupported_small_number", "wrong", ROI_Q, "Return on investment is 15000 divided by 60000, which is 25%, and the firm has two competitors.", P_ROI,
     spec([inp("np", "net profit", "15000"), inp("ci", "cost of the investment", "60000")],
          [step("roi", "return on investment", "np / ci")], "25", "%"), "BLOCK"),
    ("w_relabelled_both_inputs", "wrong", "A bakery has takings of 800 and expenses of 520. What is its gross margin?",
     "Gross profit is 280, so gross margin is 280 divided by 800, which is 35%.", P_GM,
     spec(GM_IN, [step("gp", "gross profit", "rev - cogs"), step("gm", "gross margin", "gp / rev")], "35", "%"), "BLOCK"),
    ("w_relabelled_one_input", "wrong", "A firm has current assets of 900 and borrowings of 600. What is the current ratio?",
     "The current ratio is 900 divided by 600, which is 1.5.", P_CR,
     spec([inp("ca", "current assets", "900"), inp("cl", "current liabilities", "600")], [step("cr", "current ratio", "ca / cl")], "1.5"),
     "BLOCK"),
    # computational, no specification
    ("o_calculate_no_spec", "omitted_spec", "Calculate the break-even quantity if fixed costs are 12000 and the contribution margin is 20 per unit.",
     "Break-even quantity is fixed costs divided by contribution margin per unit, which is 600.", P_BE, None, "BLOCK"),
    ("o_derived_no_verb", "omitted_spec", "Sales rise from 40 to 50. By what percentage did they change?",
     "They changed by 25 percent, which is the change divided by the original value.", P_PCT, None, "BLOCK"),
    ("o_result_in_passage", "omitted_spec", "A firm has revenue of 800 and cost of goods sold of 520; calculate its gross profit.",
     "Gross profit is revenue minus cost of goods sold, which is 280.", P_GP_EXAMPLE, None, "BLOCK"),
    # legitimate non-computational questions with numbers
    ("n_rule_of_thumb", "non_computational", "What current ratio is conventionally considered healthy?",
     "A current ratio of about 2 is conventionally considered healthy.", P_CR, None, "ACCEPT"),
    ("n_year", "non_computational", "In which year did the firm adopt the new reporting standard?",
     "The firm adopted the new reporting standard in 2019.",
     "The firm adopted the new reporting standard in 2019 after a review lasting 18 months.", None, "ACCEPT"),
    ("n_four_ps", "non_computational", "What are the elements of the marketing mix?",
     "The marketing mix has four elements: product, price, place and promotion.",
     "The marketing mix has four elements: product, price, place and promotion.", None, "ACCEPT"),
    ("n_thin_margin", "non_computational", "Why is a margin of 5 percent considered thin in grocery retail?",
     "Volumes are high and prices are competitive, so a 5 percent margin is thin.",
     "A margin of 5 percent is considered thin in grocery retail because volumes are high and prices are competitive.", None, "ACCEPT"),
]
