"""Original synthetic source packs for Business Tutoring Evaluation V1.

Ten short packs, two per subject. Everything here was written for this evaluation: no lecture notes,
textbook text or other copyrighted material, and every firm is fictional. Each pack has three "pages":

  page 1  the concept (definitions and rules)
  page 2  a short business scenario
  page 3  a related-but-different concept (a decoy: similar vocabulary, different idea)

Frozen before any evaluation run (see frozen.sha256).
"""

from __future__ import annotations

PACKS: dict[str, dict] = {
    "ACC-1": {
        "subject": "Accounting", "source_id": "acc1-src", "concept": "accrual accounting and the matching principle",
        "pages": [
            "Accrual accounting records revenue when it is earned and expenses when they are incurred, regardless of "
            "when cash is received or paid. The matching principle requires expenses to be recorded in the same "
            "period as the revenues they helped to generate. Accrual accounting therefore gives a fuller picture of "
            "performance in a period than cash accounting, which records transactions only when cash changes hands.",
            "Harbour Print Ltd delivers a large printing job to a customer in December and sends an invoice due in "
            "February. It pays its staff for December work in January. Under accrual accounting the printing revenue "
            "and the December wages both belong to December, even though no cash was received and the wages were "
            "paid in January. Under cash accounting December would show no revenue, so profit would look "
            "misleadingly different.",
            "Inventory valuation methods such as first-in first-out and weighted average cost determine the cost of "
            "goods sold. In a period of rising prices, first-in first-out reports a lower cost of goods sold and a "
            "higher profit than weighted average cost.",
        ],
    },
    "ACC-2": {
        "subject": "Accounting", "source_id": "acc2-src", "concept": "depreciation",
        "pages": [
            "Depreciation allocates the cost of a long-lived asset over its useful life. It is an allocation of "
            "cost, not a measure of the fall in the asset's market value, and it involves no cash payment in the "
            "period. Straight-line depreciation charges an equal amount each year: cost less residual value, "
            "divided by useful life. Depreciation expense reduces profit and the carrying amount of the asset on "
            "the balance sheet.",
            "Calder Logistics buys a delivery van with a high cost and a small residual value, and expects to use it "
            "for five years. Straight-line depreciation charges the same expense in each of the five years. After "
            "two years the van's carrying amount is its cost less accumulated depreciation, which may differ from "
            "what the van could be sold for. The depreciation charge does not require Calder to pay any cash in "
            "those years.",
            "The current ratio compares current assets with current liabilities. A ratio below one suggests that "
            "short-term obligations exceed liquid resources, so the firm may struggle to pay its suppliers on time.",
        ],
    },
    "FIN-1": {
        "subject": "Finance", "source_id": "fin1-src", "concept": "net present value",
        "pages": [
            "Net present value is the sum of the present values of a project's expected cash flows, discounted at "
            "the required rate of return, minus the initial investment. The decision rule is to accept projects "
            "with a positive net present value, because they are expected to add value for shareholders. Cash flows "
            "are discounted because money received sooner can be invested and is worth more than the same amount "
            "received later. A higher discount rate lowers the net present value.",
            "Nordvik Foods is considering a new packaging line that needs a large upfront investment and promises "
            "cash savings over six years. Management notes that the project's net present value is positive at the "
            "company's required rate of return but would turn negative if the discount rate rose sharply, because "
            "most of the savings arrive in the later years.",
            "The payback period is the time taken for a project's cash flows to repay the initial investment. It "
            "ignores the timing of cash flows within the payback period and ignores all cash flows after it, so it "
            "can reject projects that create value.",
        ],
    },
    "FIN-2": {
        "subject": "Finance", "source_id": "fin2-src", "concept": "systematic and unsystematic risk",
        "pages": [
            "The total risk of a share has two parts. Unsystematic risk is specific to one firm or industry, such as "
            "a product recall or a strike, and can be reduced by holding many shares in a diversified portfolio. "
            "Systematic risk comes from economy-wide factors such as interest rates and recessions, affects all "
            "shares to some degree and cannot be removed by diversification. Beta measures a share's sensitivity "
            "to systematic risk, and investors are compensated only for bearing systematic risk.",
            "An investor holds only the shares of Tidewell Airlines. A fuel-price shock and a pilot strike both hit "
            "the airline, and her wealth falls sharply. A friend who spread the same savings across thirty firms "
            "in different industries lost far less from the strike, though both investors suffered when a recession "
            "cut share prices across the whole market.",
            "Bonds pay fixed coupons and return their face value at maturity. When market interest rates rise, the "
            "price of an existing bond falls, because its fixed coupons are less attractive than those of new bonds.",
        ],
    },
    "ECO-1": {
        "subject": "Economics", "source_id": "eco1-src", "concept": "opportunity cost and sunk costs",
        "pages": [
            "Opportunity cost is the value of the best alternative given up when a choice is made. Rational decision "
            "makers compare marginal benefit with marginal cost and continue an activity while marginal benefit "
            "exceeds marginal cost. Sunk costs, which have already been incurred and cannot be recovered, should be "
            "ignored because they do not change the choice between alternatives going forward.",
            "Maple Bakery is reluctant to cancel an unprofitable oven project because a non-refundable deposit is "
            "already paid. An advisor points out that the deposit is a sunk cost, and that the decision should "
            "compare the additional revenue the project will bring with its additional cost, including the best "
            "alternative use of the money.",
            "A shift in the supply curve to the right lowers the equilibrium price and raises the equilibrium "
            "quantity, other things equal. A shift in the demand curve to the right raises both the equilibrium "
            "price and the equilibrium quantity.",
        ],
    },
    "ECO-2": {
        "subject": "Economics", "source_id": "eco2-src", "concept": "price elasticity of demand",
        "pages": [
            "Price elasticity of demand measures how strongly the quantity demanded responds to a change in price. "
            "Demand is elastic when quantity falls proportionally more than price rises, and inelastic when it "
            "falls proportionally less. If demand is elastic, a price increase reduces total revenue; if demand is "
            "inelastic, a price increase raises total revenue. Demand tends to be more elastic when close "
            "substitutes are available and when the good is a luxury rather than a necessity.",
            "A regional rail operator raises commuter fares on a line with no alternative route, and ridership "
            "falls only slightly. On a leisure route that competes with coach services, the same fare rise causes "
            "many passengers to switch to coaches, and revenue falls.",
            "Cross-price elasticity of demand measures how the quantity demanded of one good responds to a change "
            "in the price of another good. It is positive for substitutes and negative for complements.",
        ],
    },
    "MKT-1": {
        "subject": "Marketing", "source_id": "mkt1-src", "concept": "segmentation, targeting and positioning",
        "pages": [
            "Segmentation, targeting and positioning form a sequence. Segmentation divides a market into groups of "
            "customers with similar needs. Targeting selects the segments a firm will serve, based on their size, "
            "growth, profitability and fit with the firm's strengths. Positioning then defines how the firm wants "
            "its offer to be perceived by the target segment relative to competitors. Segments should be "
            "measurable, accessible and large enough to be worth serving.",
            "Verde Cycles sells electric bikes. It finds one group of urban commuters who value reliability and a "
            "second group of weekend leisure riders who value comfort. The firm chooses to target commuters because "
            "that segment is larger, growing and fits its engineering strengths, and it positions its bikes as the "
            "dependable daily commute.",
            "The marketing mix comprises product, price, place and promotion. A firm sets each element to serve its "
            "chosen customers, and the four elements should be consistent with one another.",
        ],
    },
    "MKT-2": {
        "subject": "Marketing", "source_id": "mkt2-src", "concept": "product life cycle",
        "pages": [
            "The product life cycle describes four stages: introduction, growth, maturity and decline. In "
            "introduction, sales are low and costs and promotion are high as awareness is built. In growth, sales "
            "and profit rise quickly and competitors enter. In maturity, sales growth slows, competition is intense "
            "and firms defend share, often through differentiation and cost control. In decline, sales fall and "
            "firms decide whether to harvest, reposition or withdraw the product. The stage is a signal for "
            "marketing strategy, not a fixed schedule.",
            "Lumen Audio sells wireless earbuds in a market where sales growth has slowed, many rival brands offer "
            "similar features, and price discounting is common. Lumen's managers debate whether to cut promotion "
            "spending and withdraw the product or to differentiate it with new features.",
            "Brand equity is the added value a brand name gives a product beyond its functional benefits. Strong "
            "brand equity lets a firm charge a price premium and makes new products easier to launch.",
        ],
    },
    "MGT-1": {
        "subject": "Management", "source_id": "mgt1-src", "concept": "Porter's five forces",
        "pages": [
            "Porter's five forces framework assesses industry attractiveness through five forces: the threat of new "
            "entrants, the bargaining power of suppliers, the bargaining power of buyers, the threat of substitutes "
            "and rivalry among existing competitors. Strong forces reduce industry profitability. High barriers to "
            "entry, such as economies of scale or strong brands, weaken the threat of new entrants. The framework "
            "analyses an industry, not a single firm, and it describes profit pressure rather than predicting any "
            "firm's failure.",
            "In the regional coffee-shop industry, setting up a shop requires little capital, customers can switch "
            "between shops at no cost, and many independent shops compete in the same streets. Suppliers of beans "
            "are numerous and offer similar products. A few customers have started using home machines instead of "
            "buying coffee.",
            "SWOT analysis lists a firm's internal strengths and weaknesses and the external opportunities and "
            "threats it faces. It is a firm-level summary and does not by itself rank which factors matter most.",
        ],
    },
    "MGT-2": {
        "subject": "Management", "source_id": "mgt2-src", "concept": "Herzberg's two-factor theory",
        "pages": [
            "Herzberg's two-factor theory separates hygiene factors from motivators. Hygiene factors, such as pay, "
            "working conditions, company policy and job security, prevent dissatisfaction when adequate but do not "
            "by themselves create motivation. Motivators, such as achievement, recognition, responsibility and the "
            "work itself, produce satisfaction and motivation. According to the theory, removing dissatisfaction is "
            "not the same as creating satisfaction, so a manager needs to attend to both groups of factors.",
            "At Brightline Call Centre, management raises salaries and improves the office, and complaints about "
            "pay fall. Six months later, staff engagement surveys show little change, and employees say their work "
            "is repetitive and offers no chance to take on responsibility or be recognised.",
            "Maslow's hierarchy of needs ranks needs from physiological to self-actualisation and suggests that a "
            "lower need must be broadly satisfied before a higher need becomes a strong motivator.",
        ],
    },
}
