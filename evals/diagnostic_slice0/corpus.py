"""Synthetic corpus and independent gold labels for Diagnostic Slice 0.

Everything here is invented teaching text. Gold labels were written from the source passages
and the intended pedagogy BEFORE any validator was run on them; they never come from validator
output. Fictional module code, fictional source ids, no student data.
"""

from __future__ import annotations

MODULE = "EVAL101"
FINGERPRINT = {"algorithm": "sha256", "value": "eval-fixture"}

# Per subject: three pages. p1 = target concept, p2 = decoy with similar vocabulary,
# p3 = unrelated page that exists in the same source.
SUBJECTS = {
    "marketing": {
        "source_id": "mkt-src", "concept": "market segmentation",
        "pages": [
            "Market segmentation divides a broad market into groups of customers who share similar needs, "
            "characteristics or behaviours. A firm segments a market so that it can design a distinct marketing "
            "mix for each group. Common bases for segmentation include demographic, geographic, psychographic "
            "and behavioural variables.",
            "Market positioning is the way a firm wants customers to perceive its product relative to competing "
            "products. A positioning statement links a target market, a frame of reference and a point of "
            "difference. Positioning follows segmentation and targeting but is a separate decision.",
            "Retail inventory turnover measures how many times stock is sold and replaced in a year. A low ratio "
            "can signal weak sales or overstocking.",
        ],
        "root_task": "What is market segmentation and why does a firm use it?",
        "root_ref": "Market segmentation divides a broad market into groups of customers with similar needs or "
                    "behaviours so a firm can design a distinct marketing mix for each group.",
        "root_unsupported": "Market segmentation means selling one identical product to the whole market at a "
                            "single low price, and it was introduced by regulators in 1950.",
        "root_contradicted": "Market segmentation combines all customers into one group that share the same needs "
                             "so a firm can use a single marketing mix, and it is based only on demographic variables.",
        "root_correct_student": "It splits a broad market into customer groups with similar needs so the firm can "
                                "design a distinct marketing mix for each group.",
        "paraphrase": "Splitting a large market into sets of buyers with common needs lets the company build a "
                      "separate offer for every set.",
        "fq": "Which kinds of variable can a firm use as bases for dividing a market into customer groups?",
        "fq_valid": "Demographic, geographic, psychographic and behavioural variables are common bases for dividing "
                    "a market into groups.",
        "fq_unsupported_tail": " Psychographic bases always double profit.",
        "fq_contradicted": "Only the demographic variable is a valid basis for dividing a market; geographic, "
                           "psychographic and behavioural variables cannot be used.",
        "fq_decoy_swap": "Positioning links a target market, a frame of reference and a point of difference, and "
                         "follows segmentation and targeting.",
        "short": {"task": "Which marketing process divides a market into customer groups?", "ref": "segmentation",
                  "leak": "The process you want is called segmentation.",
                  "clean": "Look again at the first page of the lecture on markets and customers."},
        "hedge_content": None,
    },
    "economics": {
        "source_id": "eco-src", "concept": "price elasticity of demand",
        "pages": [
            "Price elasticity of demand measures how responsive the quantity demanded is to a change in price. It "
            "is calculated as the percentage change in quantity demanded divided by the percentage change in "
            "price. Because demand curves slope downward the value is negative, and demand is called elastic when "
            "its absolute value exceeds one.",
            "Income elasticity of demand measures how responsive the quantity demanded is to a change in consumer "
            "income. It is calculated as the percentage change in quantity demanded divided by the percentage "
            "change in income. A normal good has a positive value and an inferior good has a negative value.",
            "Gross domestic product is the market value of all final goods and services produced within a country "
            "in a given period.",
        ],
        "root_task": "What does price elasticity of demand measure and how is it calculated?",
        "root_ref": "It measures how responsive quantity demanded is to a price change, calculated as the percentage "
                    "change in quantity demanded divided by the percentage change in price.",
        "root_unsupported": "It measures how much a firm's profit changes when wages rise, and it is calculated by "
                            "multiplying price by output.",
        "root_contradicted": "It measures how responsive quantity demanded is to a price change, calculated as the "
                             "percentage change in price divided by the percentage change in quantity demanded.",
        "root_correct_student": "It shows how responsive the quantity demanded is to a price change: the percentage "
                                "change in quantity demanded divided by the percentage change in price.",
        "paraphrase": "Think of it as how strongly buyers alter what they purchase when the price moves: the "
                      "proportional drop in purchases over the proportional price rise.",
        "fq": "How does the sign of price elasticity of demand arise, and when is demand called elastic?",
        "fq_valid": "Because demand curves slope downward the value is negative, and demand is elastic when its "
                    "absolute value exceeds one.",
        "fq_unsupported_tail": " Elastic demand always guarantees higher profit.",
        "fq_contradicted": "Because demand curves slope upward the value is positive, and demand is elastic when its "
                           "absolute value is below one.",
        "fq_decoy_swap": "A normal good has a positive income elasticity of demand and an inferior good has a "
                         "negative value, measured against consumer income.",
        "short": {"task": "If quantity demanded falls 20% when price rises 10%, what is the price elasticity of demand?",
                  "ref": "-2", "leak": "The answer is -2.", "numeric_para": "It works out to minus two.",
                  "clean": "Check the worked example on page 2 of the source."},
        "hedge_content": None,
    },
    "statistics": {
        "source_id": "sta-src", "concept": "standard error of the mean",
        "pages": [
            "The standard error of the mean describes how much sample means vary from sample to sample. It is "
            "calculated as the sample standard deviation divided by the square root of the sample size. A larger "
            "sample therefore gives a smaller standard error.",
            "The standard deviation describes how far individual observations typically fall from the mean of a "
            "sample. It is calculated from the squared deviations of observations around the mean. A larger spread "
            "of values gives a larger standard deviation.",
            "A p-value is the probability of data at least as extreme as those observed if the null hypothesis "
            "were true.",
        ],
        "root_task": "What is the standard error of the mean and how is it calculated?",
        "root_ref": "It describes how much sample means vary from sample to sample and is calculated as the sample "
                    "standard deviation divided by the square root of the sample size.",
        "root_unsupported": "It is the largest error a researcher can make in a survey, and it is equal to the "
                            "sample size divided by the population.",
        "root_contradicted": "It describes how much sample means vary from sample to sample and is calculated as the "
                             "sample standard deviation multiplied by the square root of the sample size.",
        "root_correct_student": "It tells you how much sample means vary between samples; you divide the sample "
                                "standard deviation by the square root of the sample size.",
        "paraphrase": "It tells you how much averages from repeated samples bounce around, found by taking the spread "
                      "of the data and dividing by the root of how many observations you have.",
        "fq": "How does the size of a sample change the standard error?",
        "fq_valid": "A larger sample gives a smaller standard error.",
        "fq_unsupported_tail": " Doubling the sample halves the error exactly.",
        "fq_contradicted": "A larger sample gives a larger standard error.",
        "fq_decoy_swap": "A larger spread of values gives a larger standard deviation.",
        "short": {"task": "A sample has standard deviation 10 and size 25. What is the standard error of the mean?",
                  "ref": "2", "leak": "The standard error is 2.",
                  "clean": "See page 2 and divide by the square root of the sample size, then check your arithmetic."},
        "hedge_content": "The sample mean is only an estimate, so the result is not certain and the standard error "
                         "describes how much it varies.",
    },
    "finance": {
        "source_id": "fin-src", "concept": "present value",
        "pages": [
            "Present value is the current worth of a sum of money to be received in the future, discounted at a "
            "required rate of return. For a single payment it equals the future value divided by one plus the "
            "discount rate, raised to the number of periods. A higher discount rate gives a lower present value.",
            "Future value is the amount an investment will grow to after earning interest over a number of periods. "
            "For a single deposit it equals the present value multiplied by one plus the interest rate, raised to "
            "the number of periods. A higher interest rate gives a higher future value.",
            "A bond is a loan to an issuer that pays periodic coupon interest and returns the face value at "
            "maturity.",
        ],
        "root_task": "What is present value?",
        "root_ref": "Present value is the current worth of a sum of money to be received in the future, discounted "
                    "at a required rate of return.",
        "root_unsupported": "Present value is the market price of a company's shares today and it is not affected "
                            "by interest rates or discounting.",
        "root_contradicted": "Present value is the amount an investment grows to in the future after earning "
                             "interest, and a higher rate gives a higher value.",
        "root_correct_student": "It is what a future sum of money is worth today, discounted at the required rate "
                                "of return.",
        "paraphrase": "It is what a payment due later is worth right now once you shrink it using the return you "
                      "demand on your money.",
        "fq": "How is the present value of a single payment calculated, and what does a higher discount rate do to it?",
        "fq_valid": "It equals the future value divided by one plus the discount rate, raised to the number of "
                    "periods, and a higher discount rate gives a lower present value.",
        "fq_unsupported_tail": " Present value always exceeds future value.",
        "fq_contradicted": "It equals the future value multiplied by one plus the discount rate, raised to the "
                           "number of periods, and a higher discount rate gives a higher present value.",
        "fq_decoy_swap": "A single deposit's future value equals the present value multiplied by one plus the "
                         "interest rate, raised to the number of periods.",
        "short": {"task": "A payment of 1100 is due in one period and the discount rate is 10%. What is its present value?",
                  "ref": "1000", "leak": "The present value is 1,000.", "numeric_para": "It comes to one thousand.",
                  "clean": "Divide by 1.10, then check your arithmetic against page 1 of the source."},
        "hedge_content": "Future cash flows are not certain, so they are discounted at a required rate of return "
                         "to give their present value.",
    },
    "psychology": {
        "source_id": "psy-src", "concept": "random assignment",
        "pages": [
            "Random assignment places participants into experimental conditions by chance, so that each participant "
            "has an equal probability of being in any condition. It makes the groups equivalent on average before "
            "the treatment, which reduces the influence of confounding variables. Random assignment is what allows "
            "an experiment to support causal conclusions.",
            "Random sampling selects participants from a population by chance so that each member has an equal "
            "probability of being chosen. It supports generalising findings from the sample to the population. "
            "Random sampling is a separate procedure from random assignment.",
            "Operational definitions state exactly how a variable is measured or manipulated in a study so that "
            "others can replicate it.",
        ],
        "root_task": "What is random assignment and what does it allow an experiment to do?",
        "root_ref": "Random assignment puts participants into conditions by chance so the groups are equivalent on "
                    "average, which reduces confounds and allows causal conclusions.",
        "root_unsupported": "Random assignment means choosing the most motivated volunteers for the treatment "
                            "condition, which proves the results generalise to every population.",
        "root_contradicted": "Random assignment selects participants from a population by chance to generalise to "
                             "it, and it cannot support causal conclusions.",
        "root_correct_student": "Participants are put into conditions by chance so the groups are equivalent on "
                                "average, which reduces confounds and lets the experiment support causal conclusions.",
        "paraphrase": "Participants are allocated to groups by a chance procedure so the groups start out equal on "
                      "average, which lets researchers draw cause-and-effect conclusions.",
        "fq": "Why does random assignment reduce the influence of confounding variables, and what does that allow?",
        "fq_valid": "It makes the groups equivalent on average before the treatment, which allows an experiment to "
                    "support causal conclusions.",
        "fq_unsupported_tail": " Random assignment also guarantees every result is true.",
        "fq_contradicted": "It makes the groups different on average before the treatment, which prevents an "
                           "experiment from supporting causal conclusions.",
        "fq_decoy_swap": "Random sampling selects participants from a population by chance, which supports "
                         "generalising findings to the population.",
        "short": {"task": "Which procedure puts participants into experimental conditions by chance?",
                  "ref": "random assignment", "leak": "The procedure is random assignment.",
                  "clean": "Think about how participants end up in each condition."},
        "hedge_content": "Participants may guess the hypothesis, which is a demand characteristic that threatens "
                         "the validity of a study.",
    },
}

# Quantitative generated follow-ups (validate_question). gold: ACCEPT = correctly derived and answerable
# from the cited page; REJECT = arithmetic or formula is wrong although it shares the page's vocabulary.
QUANT = {
    "economics": {
        "question": "Quantity demanded falls by 20% when price rises by 10%. What is the price elasticity of "
                    "demand, and is demand elastic?",
        "valid": "The value is minus 20 divided by 10, which is negative 2, and demand is elastic because its "
                 "absolute value exceeds one.",
        "wrong_arith": "The value is minus 10 divided by 20, which is negative 0.5, and demand is elastic because "
                       "its absolute value exceeds one.",
        "wrong_formula": "The value is 20 multiplied by 10, which is 200, and demand is elastic because its "
                         "absolute value exceeds one.",
    },
    "statistics": {
        "question": "A sample has standard deviation 10 and size 25. What is the standard error of the mean?",
        "valid": "The standard error is the sample standard deviation divided by the square root of the sample "
                 "size, 10 divided by 5, which is 2.",
        "wrong_arith": "The standard error is the sample standard deviation divided by the square root of the "
                       "sample size, 10 divided by 25, which is 0.4.",
        "wrong_formula": "The standard error is the sample standard deviation multiplied by the square root of "
                         "the sample size, 10 multiplied by 5, which is 50.",
    },
    "finance": {
        "question": "A payment of 1100 is due in one period and the discount rate is 10%. What is its present value?",
        "valid": "Present value equals the future value divided by one plus the discount rate, so 1100 divided by "
                 "1.10 is 1000.",
        "wrong_arith": "Present value equals the future value divided by one plus the discount rate, so 1100 "
                       "divided by 1.10 is 1100.",
        "wrong_formula": "Present value equals the future value multiplied by one plus the discount rate, so 1100 "
                         "multiplied by 1.10 is 1210.",
    },
}
