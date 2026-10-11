"""Frozen task definitions and expected outcomes for Business Tutoring Evaluation V1.

Everything here (reference answers, reference explanations, common misconceptions, scripted student responses,
expected outcomes) was written from the source packs and the intended pedagogy BEFORE any production code was
run on it. Expected outcomes are never taken from production output. See frozen.sha256.

Student response kinds and the outcome the production policy is *intended* to produce for each:
"""

from __future__ import annotations

# kind -> (diagnosis, hedged, non_answer, next_action, plan_step, plan_reason, model_should_be_called)
EXPECTED_BY_KIND = {
    "correct":        ("correct",    False, False, "CONSOLIDATE",     "TRANSFER",  "CORRECT_ANSWER",   True),
    "correct_hedged": ("correct",    True,  False, "CHECK_REASONING", "FOLLOW_UP", "REASONING_CHECK", True),
    "partial":        ("partial",    False, False, "FOLLOW_UP",       "FOLLOW_UP", "PARTIAL_ANSWER",   True),
    "misconception":  ("misconception", False, False, "REVIEW_SOURCE", "FOLLOW_UP", "MISCONCEPTION",  True),
    "off_topic":      ("off_target", False, False, "RESTATE",         "FOLLOW_UP", "OFF_TARGET",       True),
    "dont_know":      ("unclear",    True,  True,  "OFFER_HINT",      "NONE",      "NEEDS_CLARITY",    False),
}

CAPABILITIES = ("CONCEPTUAL_TEACHING", "MISCONCEPTION_DIAGNOSIS", "CASE_STUDY_APPLICATION", "ASSESSMENT_PREPARATION")


def R(kind, text, quote=None, label=None, missing=None):
    """One scripted student response. ``quote``/``label`` only for kind=misconception; ``missing`` = reasoning steps
    a good tutor should name for a partial case-study answer (judged later, not here)."""
    return {"kind": kind, "text": text, "quote": quote, "label": label, "missing_steps": missing or []}


def Q(kind, gold, question, expected, pages):
    """One scripted generated follow-up question and whether it SHOULD be shown to a student."""
    return {"kind": kind, "gold": gold, "question": question, "expected_answer": expected, "pages": pages,
            "after": "correct" if kind == "good_transfer" else "partial"}


TASKS: list[dict] = [
    # ------------------------------------------------------------------ CONCEPTUAL TEACHING
    {"id": "CT-ACC1", "capability": "CONCEPTUAL_TEACHING", "pack": "ACC-1", "cite_pages": [1],
     "root_task": "Explain how accrual accounting differs from cash accounting and why the matching principle matters.",
     "reference": "Accrual accounting records revenue when it is earned and expenses when they are incurred, regardless "
                  "of when cash is received or paid. The matching principle requires expenses to be recorded in the "
                  "same period as the revenues they helped to generate, which gives a fuller picture of performance "
                  "than cash accounting.",
     "reference_explanation": "Profit for a period should reflect what the firm earned and what it spent to earn it, not "
                              "when cash happened to move. Accrual accounting achieves this; cash accounting can shift "
                              "profit between periods.",
     "common_misconceptions": ["Accrual accounting records transactions when cash is received.",
                               "Matching means income and expenses must be equal."],
     "responses": [
         R("correct", "Accrual accounting books income when it is earned and costs when they are incurred, whatever the "
                      "timing of cash. Matching puts expenses in the same period as the revenue they helped create, so "
                      "performance looks fairer than under cash accounting."),
         R("partial", "Accrual accounting records revenue when it is earned rather than when cash arrives."),
         R("off_topic", "Accounting software lets firms file their tax returns on time each year.")],
     "leak_paraphrase": None, "guidance": None},
    {"id": "CT-ACC2", "capability": "CONCEPTUAL_TEACHING", "pack": "ACC-2", "cite_pages": [1],
     "root_task": "What is depreciation and how does straight-line depreciation work?",
     "reference": "Depreciation allocates the cost of a long-lived asset over its useful life. Straight-line depreciation "
                  "charges an equal amount each year: cost less residual value, divided by useful life.",
     "reference_explanation": "Depreciation spreads what the firm paid for an asset across the years it helps earn revenue; "
                              "straight-line is the simplest pattern because each year bears the same charge.",
     "common_misconceptions": ["Depreciation is the fall in the asset's market price.",
                               "Straight-line depreciation ignores residual value."],
     "responses": [
         R("correct", "It spreads the cost of an asset over its useful life. With straight-line you take cost minus "
                      "residual value and divide by the useful life, so every year gets the same charge."),
         R("partial", "Depreciation spreads the cost of an asset over the years it is used."),
         R("off_topic", "A firm should sell its old assets whenever a competitor buys new ones.")],
     "leak_paraphrase": None, "guidance": None},
    {"id": "CT-FIN1", "capability": "CONCEPTUAL_TEACHING", "pack": "FIN-1", "cite_pages": [1],
     "root_task": "State the net present value decision rule and explain why cash flows are discounted.",
     "reference": "Accept projects with a positive net present value, because they are expected to add value for "
                  "shareholders. Cash flows are discounted because money received sooner can be invested and is worth "
                  "more than the same amount received later.",
     "reference_explanation": "A pound today can earn a return, so a pound promised later is worth less now. NPV converts "
                              "all cash flows to today's value so they can be compared with the investment.",
     "common_misconceptions": ["Discounting is only about inflation.", "Accept any project with positive total cash flow."],
     "responses": [
         R("correct", "Take projects whose net present value is positive since they should add value for shareholders. "
                      "We discount because money received sooner can be invested, so it is worth more than the same "
                      "amount later."),
         R("correct_hedged", "I think you accept a project when its net present value is positive, because it should add "
                             "value for shareholders, and cash is discounted because money received sooner is worth "
                             "more than the same amount later."),
         R("partial", "You accept projects with a positive net present value."),
         R("dont_know", "I don't know, sorry.")],
     "leak_paraphrase": None, "guidance": None},
    {"id": "CT-ECO2", "capability": "CONCEPTUAL_TEACHING", "pack": "ECO-2", "cite_pages": [1],
     "root_task": "Define price elasticity of demand and explain what elasticity implies for total revenue when price rises.",
     "reference": "Price elasticity of demand measures how strongly the quantity demanded responds to a change in price. If "
                  "demand is elastic, a price increase reduces total revenue; if demand is inelastic, a price increase "
                  "raises total revenue.",
     "reference_explanation": "Revenue is price times quantity. A price rise helps revenue only if quantity falls by "
                              "proportionally less than price rises.",
     "common_misconceptions": ["Elasticity is the same as the slope of the demand curve.",
                               "A price rise always increases revenue."],
     "responses": [
         R("correct", "It measures how strongly quantity demanded reacts to a price change. When demand is elastic a price "
                      "rise cuts total revenue, and when it is inelastic a price rise raises total revenue."),
         R("partial", "Elasticity measures how strongly the quantity demanded responds to a change in price."),
         R("off_topic", "Supply chains are disrupted when ports are congested.")],
     "leak_paraphrase": None, "guidance": None},
    {"id": "CT-MKT2", "capability": "CONCEPTUAL_TEACHING", "pack": "MKT-2", "cite_pages": [1],
     "root_task": "Name the four stages of the product life cycle and describe what happens to sales in each.",
     "reference": "The stages are introduction, growth, maturity and decline. Sales are low in introduction, rise quickly in "
                  "growth, slow in maturity and fall in decline.",
     "reference_explanation": "The cycle describes typical sales patterns and signals which marketing priorities fit; it is "
                              "not a fixed timetable and not every product follows it.",
     "common_misconceptions": ["Every product moves through each stage on a fixed schedule.",
                               "Decline always means the product must be withdrawn."],
     "responses": [
         R("correct", "Introduction, growth, maturity and decline. Sales are low at introduction, rise quickly in growth, "
                      "slow down in maturity and fall in decline."),
         R("partial", "Introduction, growth, maturity and decline."),
         R("dont_know", "no idea")],
     "leak_paraphrase": None, "guidance": None},
    {"id": "CT-MGT2", "capability": "CONCEPTUAL_TEACHING", "pack": "MGT-2", "cite_pages": [1],
     "root_task": "Distinguish hygiene factors from motivators in Herzberg's two-factor theory.",
     "reference": "Hygiene factors, such as pay and working conditions, prevent dissatisfaction when adequate but do not by "
                  "themselves create motivation, whereas motivators, such as achievement, recognition and responsibility, "
                  "produce satisfaction and motivation.",
     "reference_explanation": "The theory treats dissatisfaction and satisfaction as separate dimensions: fixing the first does "
                              "not deliver the second.",
     "common_misconceptions": ["Pay is the main motivator.", "Hygiene factors are unimportant."],
     "responses": [
         R("correct", "Hygiene factors like pay and working conditions stop dissatisfaction when they are adequate but do not "
                      "motivate by themselves, while motivators like achievement, recognition and responsibility create "
                      "satisfaction and motivation."),
         R("partial", "Hygiene factors such as pay and working conditions prevent dissatisfaction."),
         R("off_topic", "Managers should always hold team meetings on Monday mornings.")],
     "leak_paraphrase": None, "guidance": None},

    # ------------------------------------------------------------------ MISCONCEPTION DIAGNOSIS
    {"id": "MD-ACC1", "capability": "MISCONCEPTION_DIAGNOSIS", "pack": "ACC-1", "cite_pages": [1],
     "root_task": "When does accrual accounting record revenue?",
     "reference": "Accrual accounting records revenue when it is earned, regardless of when cash is received.",
     "reference_explanation": "Revenue is recognised on earning it (for example delivering the job), even if payment follows "
                              "weeks later.",
     "common_misconceptions": ["Revenue is recorded when the customer pays."],
     "responses": [
         R("misconception", "Revenue is recorded when the customer pays the cash, otherwise you have not really got it.",
           quote="when the customer pays the cash", label="Ties revenue recognition to cash receipt"),
         R("correct", "When it is earned, for example once the work is delivered, even if the customer pays later."),
         R("dont_know", "not sure")],
     "leak_paraphrase": "Revenue gets booked at the point it has been earned, whenever the money actually arrives.",
     "guidance": "Compare what the passage says triggers recording with what triggers a cash receipt, and ask whether they are "
                 "the same event."},
    {"id": "MD-ACC2", "capability": "MISCONCEPTION_DIAGNOSIS", "pack": "ACC-2", "cite_pages": [1],
     "root_task": "Does depreciation measure the fall in an asset's market value, and does it involve a cash payment?",
     "reference": "Depreciation allocates the cost of a long-lived asset over its useful life. It is an allocation of cost, not "
                  "a measure of the fall in the asset's market value, and it involves no cash payment in the period.",
     "reference_explanation": "Depreciation is an accounting allocation; market value and cash are separate matters.",
     "common_misconceptions": ["Depreciation equals the drop in market value.", "Depreciation is a cash outflow each year."],
     "responses": [
         R("misconception", "Depreciation shows how much the asset's market value has dropped, and the company pays that "
                            "amount in cash each year.",
           quote="market value has dropped", label="Treats depreciation as market-value loss paid in cash"),
         R("correct", "It just spreads the asset's cost across its useful life; it is not about market value and no cash "
                      "leaves the business in that period."),
         R("correct_hedged", "I think it is only an allocation of cost over the useful life, not market value, and no cash is paid.")],
     "leak_paraphrase": "Spreading what a long-lived asset cost over the years it is used is the idea, and it neither tracks "
                        "resale price nor moves any money out.",
     "guidance": "Ask which of the two ideas, spreading a past cost or tracking what the asset would fetch today, the passage "
                 "says depreciation is."},
    {"id": "MD-FIN1", "capability": "MISCONCEPTION_DIAGNOSIS", "pack": "FIN-1", "cite_pages": [1],
     "root_task": "What happens to a project's net present value when the discount rate rises?",
     "reference": "A higher discount rate lowers the net present value of a project's expected cash flows.",
     "reference_explanation": "Raising the rate shrinks the present value of future cash flows while the initial investment is "
                              "unchanged.",
     "common_misconceptions": ["A higher discount rate raises NPV because the number is bigger."],
     "responses": [
         R("misconception", "A higher discount rate raises the net present value because the cash flows are discounted at a "
                            "bigger rate, so the total grows.",
           quote="raises the net present value", label="Reverses the effect of the discount rate on NPV"),
         R("correct", "It falls: a higher discount rate lowers the present value of the expected cash flows, so net present value goes down."),
         R("dont_know", "idk")],
     "leak_paraphrase": None,
     "guidance": "Think about what discounting does to a cash flow that arrives later, and what a larger rate does to that effect."},
    {"id": "MD-FIN2", "capability": "MISCONCEPTION_DIAGNOSIS", "pack": "FIN-2", "cite_pages": [1],
     "root_task": "Can diversification remove all the risk of holding shares? Explain.",
     "reference": "No. Diversification reduces unsystematic risk, which is specific to one firm or industry, but systematic "
                  "risk comes from economy-wide factors and cannot be removed by diversification.",
     "reference_explanation": "Firm-specific events average out across many shares; recessions and interest-rate moves hit "
                              "the whole market.",
     "common_misconceptions": ["Enough shares in different industries make all risk disappear."],
     "responses": [
         R("misconception", "Yes, if you hold enough shares in different industries then every kind of risk disappears, "
                            "including recessions.",
           quote="every kind of risk disappears", label="Believes diversification eliminates systematic risk"),
         R("correct", "Not all of it. Holding many shares cuts the risk specific to one company or industry, but economy-wide "
                      "risk such as interest rates or a recession stays."),
         R("partial", "Diversification lowers the risk from individual companies."),
         R("dont_know", "not sure")],
     "leak_paraphrase": "It trims the dangers peculiar to a single company or sector, yet dangers coming from the wider economy "
                        "stay with the investor regardless of how many holdings there are.",
     "guidance": "Sort the risks in the passage into those tied to one firm and those tied to the whole economy, then ask which "
                 "group more holdings can shrink."},
    {"id": "MD-ECO1", "capability": "MISCONCEPTION_DIAGNOSIS", "pack": "ECO-1", "cite_pages": [1],
     "root_task": "Should a sunk cost influence whether a firm continues a project?",
     "reference": "No. A sunk cost has already been incurred and cannot be recovered, so it should be ignored; the decision "
                  "should compare marginal benefit with marginal cost going forward.",
     "reference_explanation": "Whatever the firm chooses now, the sunk amount is gone; only future costs and benefits differ "
                              "between the options.",
     "common_misconceptions": ["Money already spent must be 'justified' by continuing."],
     "responses": [
         R("misconception", "Yes, the firm already paid so much that it has to keep going or the money is wasted.",
           quote="has to keep going", label="Lets a sunk cost drive the decision"),
         R("correct", "No, money already spent and unrecoverable should not count; look at the extra benefit versus the extra "
                      "cost from now on."),
         R("correct_hedged", "I think no, because that money is gone either way and only future costs and benefits matter.")],
     "leak_paraphrase": "Costs that are already spent and can't come back shouldn't sway the choice; weigh the additional gain "
                        "against the additional cost from here on.",
     "guidance": "Ask whether the sunk amount differs between continuing and stopping, and what does differ between them."},
    {"id": "MD-ECO2", "capability": "MISCONCEPTION_DIAGNOSIS", "pack": "ECO-2", "cite_pages": [1],
     "root_task": "If a firm raises its price, will total revenue always rise?",
     "reference": "No. If demand is elastic, a price increase reduces total revenue; if demand is inelastic, a price increase "
                  "raises total revenue.",
     "reference_explanation": "Revenue depends on both price and quantity, and elasticity tells you how far quantity drops.",
     "common_misconceptions": ["A higher price on every unit must mean more revenue."],
     "responses": [
         R("misconception", "Yes, a higher price on every unit sold means more money coming in, whatever customers do.",
           quote="more money coming in", label="Ignores the quantity response to a price rise"),
         R("correct", "No, it depends on elasticity: with elastic demand a price rise cuts revenue, with inelastic demand it raises revenue."),
         R("partial", "It depends on how customers react to the price.")],
     "leak_paraphrase": "A rise in price can lift or lower takings: where buyers are very responsive takings drop, and where "
                        "they are not responsive takings grow.",
     "guidance": "Revenue is price multiplied by quantity. Ask what happens to quantity when price rises and when that matters most."},
    {"id": "MD-MGT2", "capability": "MISCONCEPTION_DIAGNOSIS", "pack": "MGT-2", "cite_pages": [1],
     "root_task": "According to Herzberg, will a manager who raises pay motivate employees by that alone?",
     "reference": "No. Pay is a hygiene factor, which prevents dissatisfaction when adequate but does not by itself create "
                  "motivation; motivators such as achievement, recognition and responsibility produce motivation.",
     "reference_explanation": "Better pay removes a source of complaint; it does not supply the interest or recognition that "
                              "drive engagement.",
     "common_misconceptions": ["Pay is the strongest motivator."],
     "responses": [
         R("misconception", "Yes, better pay is the strongest motivator and makes staff more engaged.",
           quote="strongest motivator", label="Treats pay as the main motivator"),
         R("correct", "No, pay prevents dissatisfaction when it is adequate but does not create motivation by itself; "
                      "achievement, recognition and responsibility do."),
         R("dont_know", "I do not know")],
     "leak_paraphrase": None,
     "guidance": "Look at which group of factors the passage places pay in, and what that group is said to do and not do."},
    {"id": "MD-MKT1", "capability": "MISCONCEPTION_DIAGNOSIS", "pack": "MKT-1", "cite_pages": [1],
     "root_task": "Is segmentation the same thing as positioning?",
     "reference": "No. Segmentation divides a market into groups of customers with similar needs, whereas positioning defines "
                  "how the firm wants its offer to be perceived by the target segment relative to competitors.",
     "reference_explanation": "Segmentation is a way of carving up the market; positioning is a choice about the image of the offer "
                              "within the chosen segment.",
     "common_misconceptions": ["Segmentation and positioning are one step."],
     "responses": [
         R("misconception", "Yes, both mean deciding how customers see the brand, so segmentation and positioning are one step.",
           quote="both mean deciding how customers see the brand", label="Merges segmentation with positioning"),
         R("correct", "No. Segmentation splits a market into groups with similar needs; positioning is how the firm wants its "
                      "offer perceived by the target segment relative to competitors."),
         R("off_topic", "Promotion budgets are usually decided by the finance team.")],
     "leak_paraphrase": None,
     "guidance": "Ask which of the two is about grouping customers and which is about how an offer is perceived, using the sequence in the passage."},

    # ------------------------------------------------------------------ CASE-STUDY APPLICATION
    {"id": "CS-ACC1", "capability": "CASE_STUDY_APPLICATION", "pack": "ACC-1", "cite_pages": [1, 2],
     "root_task": "Harbour Print delivers a large job in December, invoices it for February and pays its December wages in "
                  "January. Under accrual accounting, which period do the revenue and the wages belong to, and why?",
     "reference": "Under accrual accounting the printing revenue and the December wages both belong to December, because "
                  "revenue is recorded when it is earned and expenses when they are incurred, even though no cash was "
                  "received and the wages were paid in January.",
     "reference_explanation": "The job was delivered and the staff worked in December, so both events fall in December; the "
                              "matching principle puts the wages in the same period as the revenue.",
     "common_misconceptions": ["Revenue belongs to February when the invoice is paid.", "Wages belong to January when paid."],
     "responses": [
         R("correct", "Both go in December: the job was delivered and the staff worked then, so revenue is earned and wages are "
                      "incurred in December even though the cash moves later."),
         R("partial", "The revenue belongs to December because the job was delivered.",
           missing=["wages are incurred in December", "matching principle links wages to the December revenue"]),
         R("off_topic", "Harbour Print should consider advertising its printing services on social media.")],
     "leak_paraphrase": None, "guidance": None},
    {"id": "CS-FIN2", "capability": "CASE_STUDY_APPLICATION", "pack": "FIN-2", "cite_pages": [1, 2],
     "root_task": "An investor holds only Tidewell Airlines shares; her friend holds thirty firms in different industries. Why "
                  "did the pilot strike hurt her far more, and why did both suffer in the recession?",
     "reference": "The investor holding only Tidewell Airlines shares bore unsystematic risk, which is specific to one firm and "
                  "which her friend reduced by holding firms in different industries; the recession is systematic risk "
                  "affecting the whole market, which diversification cannot remove.",
     "reference_explanation": "The strike is firm-specific and diversifiable; the recession is economy-wide and is not.",
     "common_misconceptions": ["The friend must have been luckier.", "Diversification would have protected both in the recession."],
     "responses": [
         R("correct", "The strike is risk specific to one firm, which the friend diversified away by holding firms in different "
                      "industries. The recession is systematic risk across the whole market, so diversification cannot remove it."),
         R("partial", "The friend spread her money over many firms so the strike hurt her less.",
           missing=["names the strike as firm-specific (unsystematic) risk", "explains why the recession is systematic and not diversifiable"]),
         R("dont_know", "i don't know")],
     "leak_paraphrase": None, "guidance": None},
    {"id": "CS-ECO2", "capability": "CASE_STUDY_APPLICATION", "pack": "ECO-2", "cite_pages": [1, 2],
     "root_task": "A rail operator raises fares. On a commuter line with no alternative route ridership barely falls; on a leisure "
                  "route competing with coaches revenue falls. Explain both outcomes using elasticity.",
     "reference": "Commuter demand is inelastic because there is no alternative route, so a fare increase raises revenue; leisure "
                  "demand is elastic because close substitutes such as coach services are available, so a fare increase reduces revenue.",
     "reference_explanation": "Availability of substitutes drives elasticity; elasticity then determines the revenue effect of a price rise.",
     "common_misconceptions": ["Leisure travellers are simply less loyal.", "The commuter fare rise must also have cut revenue."],
     "responses": [
         R("correct", "Commuters have no alternative route so demand is inelastic and the fare rise raises revenue. Leisure "
                      "passengers can use coach services as close substitutes, so demand is elastic and the same rise reduces revenue."),
         R("partial", "Commuters have no alternative so they keep travelling.",
           missing=["labels commuter demand inelastic", "links inelastic demand to higher revenue", "explains the leisure route via substitutes and elastic demand"]),
         R("correct_hedged", "I think commuter demand is inelastic because there is no alternative route, so revenue rises, and leisure "
                             "demand is elastic because coach services are close substitutes, so revenue falls.")],
     "leak_paraphrase": None, "guidance": None},
    {"id": "CS-MKT1", "capability": "CASE_STUDY_APPLICATION", "pack": "MKT-1", "cite_pages": [1, 2],
     "root_task": "Verde Cycles found urban commuters and weekend leisure riders. Why did it target commuters, and how does it "
                  "position its bikes?",
     "reference": "Verde Cycles targets the commuter segment because it is larger, growing and fits the firm's engineering "
                  "strengths, and it positions its bikes as the dependable daily commute for that target segment.",
     "reference_explanation": "Targeting applies size, growth and fit criteria; positioning then states how the offer should be "
                              "perceived by the chosen segment.",
     "common_misconceptions": ["The firm should serve both segments equally.", "Positioning is the choice of segment."],
     "responses": [
         R("correct", "It targeted commuters because that segment is larger, growing and fits its engineering strengths, and it "
                      "positions the bikes as the dependable daily commute for that target segment."),
         R("partial", "It chose commuters because they are a bigger group.",
           missing=["growth and fit with engineering strengths as targeting criteria", "states the positioning (dependable daily commute)"]),
         R("off_topic", "Electric bikes should be sold at a lower price than petrol scooters.")],
     "leak_paraphrase": None, "guidance": None},
    {"id": "CS-MGT1", "capability": "CASE_STUDY_APPLICATION", "pack": "MGT-1", "cite_pages": [1, 2],
     "root_task": "Using Porter's five forces, assess how attractive the regional coffee-shop industry is.",
     "reference": "The industry looks unattractive: little capital means a high threat of new entrants, customers switch at no "
                  "cost so buyer power is strong, many independent shops make rivalry intense, and home machines are a "
                  "substitute, while numerous suppliers offering similar products leave supplier power weak.",
     "reference_explanation": "Four forces are strong and one (suppliers) is weak, so profit pressure is high. The framework "
                              "describes the industry, not any one shop's fate.",
     "common_misconceptions": ["Strong forces mean every shop will fail."],
     "responses": [
         R("correct", "Unattractive: little capital means a high threat of new entrants, customers switch at no cost so buyer "
                      "power is strong, many independent shops make rivalry intense, and home machines are a substitute. "
                      "Numerous suppliers offering similar products leave supplier power weak."),
         R("partial", "There are many shops competing in the same streets, so rivalry is intense.",
           missing=["threat of new entrants", "buyer power", "threat of substitutes", "supplier power", "overall verdict on attractiveness"]),
         R("dont_know", "no clue")],
     "leak_paraphrase": None, "guidance": None},
    {"id": "CS-MKT2", "capability": "CASE_STUDY_APPLICATION", "pack": "MKT-2", "cite_pages": [1, 2],
     "root_task": "Lumen Audio's earbud sales growth has slowed, rivals offer similar features and discounting is common. Which "
                  "life-cycle stage is this, and which strategy fits?",
     "reference": "This is the maturity stage: sales growth slows, competition is intense and price discounting is common, so "
                  "firms defend share through differentiation and cost control rather than simply withdrawing the product.",
     "reference_explanation": "Slow growth plus intense competition is maturity. The stage signals strategy; it does not dictate "
                              "withdrawal.",
     "common_misconceptions": ["Slowing growth means decline and withdrawal."],
     "responses": [
         R("correct", "This is maturity: growth slows, competition is intense and discounting is common, so Lumen should defend "
                      "share through differentiation and cost control rather than simply withdrawing."),
         R("partial", "It sounds like maturity because growth has slowed.",
           missing=["competition and discounting as maturity signals", "differentiation and cost control as the strategic response", "why withdrawal is not automatic"]),
         R("off_topic", "Lumen Audio should hire more engineers.")],
     "leak_paraphrase": None, "guidance": None},

    # ------------------------------------------------------------------ ASSESSMENT PREPARATION
    {"id": "AP-ACC2", "capability": "ASSESSMENT_PREPARATION", "pack": "ACC-2", "cite_pages": [1],
     "root_task": "How does depreciation affect an asset's carrying amount?",
     "reference": "Depreciation expense reduces profit and the carrying amount of the asset on the balance sheet.",
     "reference_explanation": "Each year's charge lowers profit and lowers the asset's balance-sheet value by the same amount.",
     "common_misconceptions": ["Carrying amount equals market value."],
     "responses": [
         R("correct", "Depreciation expense lowers profit and also lowers the carrying amount of the asset on the balance sheet."),
         R("partial", "It reduces profit.")],
     "questions": [
         Q("good_transfer", "ACCEPT",
           "Calder Logistics expects to use a van for five years; why might its carrying amount after two years differ from what the van could be sold for?",
           "The carrying amount is its cost less accumulated depreciation, which may differ from what the van could be sold for.", [2]),
         Q("good_followup", "ACCEPT", "What does straight-line depreciation charge in each year?",
           "Straight-line depreciation charges an equal amount each year: cost less residual value, divided by useful life.", [1]),
         Q("off_concept", "REJECT", "How does first-in first-out affect cost of goods sold when prices rise?",
           "In a period of rising prices, first-in first-out reports a lower cost of goods sold and a higher profit than weighted average cost.", [3]),
         Q("unsupported_answer", "REJECT", "How long should a delivery van normally last before replacement?",
           "A delivery van normally lasts about ten years before it needs replacing.", [2]),
         Q("reworded", "REJECT", "In what way does depreciation change the carrying amount of an asset?",
           "Depreciation expense reduces profit and the carrying amount of the asset on the balance sheet.", [1]),
         Q("leaky", "REJECT", "Since depreciation expense reduces profit and the carrying amount of the asset on the balance sheet, which yearly charge does straight-line use?",
           "Straight-line depreciation charges an equal amount each year.", [1])],
     "leak_paraphrase": None, "guidance": None},
    {"id": "AP-FIN2", "capability": "ASSESSMENT_PREPARATION", "pack": "FIN-2", "cite_pages": [1],
     "root_task": "What is unsystematic risk and how can an investor reduce it?",
     "reference": "Unsystematic risk is specific to one firm or industry and can be reduced by holding many shares in a "
                  "diversified portfolio.",
     "reference_explanation": "Firm-specific events such as a strike or a recall wash out across many holdings.",
     "common_misconceptions": ["Unsystematic risk is the same as total risk."],
     "responses": [
         R("correct", "It is risk specific to one firm or industry, and an investor can reduce it by holding many shares in a diversified portfolio."),
         R("partial", "It is the risk of one firm.")],
     "questions": [
         Q("good_transfer", "ACCEPT",
           "Why did the investor holding only Tidewell Airlines lose more from the pilot strike than a friend who held thirty firms in different industries?",
           "The strike was a risk specific to one firm, which the friend reduced by holding firms in different industries.", [1, 2]),
         Q("good_followup", "ACCEPT", "What does beta measure for a share?",
           "Beta measures a share's sensitivity to systematic risk.", [1]),
         Q("off_concept", "REJECT", "How does a rise in market interest rates change the price of an existing bond?",
           "When market interest rates rise, the price of an existing bond falls, because its fixed coupons are less attractive than those of new bonds.", [3]),
         Q("unsupported_answer", "REJECT", "Which industry has the lowest beta?",
           "Utilities have the lowest beta of any industry.", [1]),
         Q("reworded", "REJECT", "What is unsystematic risk, and how can an investor cut it?",
           "Unsystematic risk is specific to one firm or industry and can be reduced by holding many shares in a diversified portfolio.", [1]),
         Q("leaky", "REJECT", "Unsystematic risk is specific to one firm or industry and can be reduced by holding many shares; which kind of risk is left?",
           "Systematic risk comes from economy-wide factors such as interest rates and recessions.", [1])],
     "leak_paraphrase": None, "guidance": None},
    {"id": "AP-ECO1", "capability": "ASSESSMENT_PREPARATION", "pack": "ECO-1", "cite_pages": [1],
     "root_task": "What is opportunity cost?",
     "reference": "Opportunity cost is the value of the best alternative given up when a choice is made.",
     "reference_explanation": "Every choice forgoes something; the cost of the choice is the value of the best thing forgone.",
     "common_misconceptions": ["Opportunity cost is the money price paid."],
     "responses": [
         R("correct", "It is the value of the best alternative that you give up when you make a choice."),
         R("partial", "It is what you give up.")],
     "questions": [
         Q("good_transfer", "ACCEPT",
           "An owner will not cancel an unprofitable project because a non-refundable deposit is already paid; what should the decision compare instead?",
           "The decision should compare the additional revenue the project will bring with its additional cost, including the best alternative use of the money.", [2]),
         Q("good_followup", "ACCEPT", "Which kind of cost should be ignored when choosing between alternatives going forward, and why?",
           "Sunk costs, which have already been incurred and cannot be recovered, should be ignored because they do not change the choice between alternatives going forward.", [1]),
         Q("off_concept", "REJECT", "How does a rightward shift in supply change the equilibrium price and quantity?",
           "A shift in the supply curve to the right lowers the equilibrium price and raises the equilibrium quantity.", [3]),
         Q("unsupported_answer", "REJECT", "Who first defined opportunity cost?",
           "Opportunity cost was first defined by an Austrian economist in the nineteenth century.", [1]),
         Q("reworded", "REJECT", "What does opportunity cost mean?",
           "Opportunity cost is the value of the best alternative given up when a choice is made.", [1]),
         Q("leaky", "REJECT", "Opportunity cost is the value of the best alternative given up when a choice is made; what does marginal analysis compare?",
           "Marginal benefit with marginal cost.", [1])],
     "leak_paraphrase": None, "guidance": None},
    {"id": "AP-MKT2", "capability": "ASSESSMENT_PREPARATION", "pack": "MKT-2", "cite_pages": [1],
     "root_task": "What happens to sales and competition in the growth stage of the product life cycle?",
     "reference": "In growth, sales and profit rise quickly and competitors enter.",
     "reference_explanation": "Growth is the stage of rapid sales and profit rises, which attracts rivals.",
     "common_misconceptions": ["Growth is when competition is most intense."],
     "responses": [
         R("correct", "In growth, sales and profit rise quickly and competitors enter the market."),
         R("partial", "Sales rise.")],
     "questions": [
         Q("good_transfer", "ACCEPT",
           "Lumen Audio sees slow growth and heavy discounting on its earbuds; should its managers simply withdraw the product?",
           "Not necessarily: they could differentiate the product with new features, as firms in maturity defend share through differentiation and cost control.", [1, 2]),
         Q("good_followup", "ACCEPT", "What do firms often do to defend share in the maturity stage?",
           "In maturity, firms defend share, often through differentiation and cost control.", [1]),
         Q("off_concept", "REJECT", "What does brand equity add to the value of a product?",
           "Brand equity is the added value a brand name gives a product beyond its functional benefits.", [3]),
         Q("unsupported_answer", "REJECT", "Which stage of the product life cycle lasts longest?",
           "Maturity lasts longest, usually for about ten years.", [1]),
         Q("reworded", "REJECT", "How do sales and competition change in the growth stage?",
           "In growth, sales and profit rise quickly and competitors enter.", [1]),
         Q("leaky", "REJECT", "In growth, sales and profit rise quickly and competitors enter; what happens to sales growth in maturity?",
           "In maturity, sales growth slows and competition is intense.", [1])],
     "leak_paraphrase": None, "guidance": None},
    {"id": "AP-MGT1", "capability": "ASSESSMENT_PREPARATION", "pack": "MGT-1", "cite_pages": [1],
     "root_task": "Name the five forces in Porter's framework.",
     "reference": "The five forces are the threat of new entrants, the bargaining power of suppliers, the bargaining power of "
                  "buyers, the threat of substitutes and rivalry among existing competitors.",
     "reference_explanation": "Entry, supplier power, buyer power, substitutes and rivalry together describe pressure on industry profit.",
     "common_misconceptions": ["SWOT and the five forces are the same tool."],
     "responses": [
         R("correct", "The threat of new entrants, the bargaining power of suppliers, the bargaining power of buyers, the threat of substitutes and rivalry among existing competitors."),
         R("partial", "New entrants, suppliers and buyers.")],
     "questions": [
         Q("good_transfer", "ACCEPT",
           "In the regional coffee-shop industry setting up a shop requires little capital; what does this imply for the threat of new entrants?",
           "Little capital means low barriers to entry, so the threat of new entrants is high.", [1, 2]),
         Q("good_followup", "ACCEPT", "How do barriers to entry affect the threat of new entrants?",
           "High barriers to entry, such as economies of scale or strong brands, weaken the threat of new entrants.", [1]),
         Q("off_concept", "REJECT", "What does a SWOT analysis list?",
           "SWOT analysis lists a firm's internal strengths and weaknesses and the external opportunities and threats it faces.", [3]),
         Q("unsupported_answer", "REJECT", "Which of the five forces is the most important in every industry?",
           "Rivalry among existing competitors is the most important force in every industry.", [1]),
         Q("reworded", "REJECT", "Which five forces make up Porter's framework?",
           "The five forces are the threat of new entrants, the bargaining power of suppliers, the bargaining power of buyers, the threat of substitutes and rivalry among existing competitors.", [1]),
         Q("leaky", "REJECT", "The threat of new entrants, the bargaining power of suppliers and of buyers are three forces; how do barriers to entry matter?",
           "High barriers to entry weaken the threat of new entrants.", [1])],
     "leak_paraphrase": None, "guidance": None},
    {"id": "AP-FIN1", "capability": "ASSESSMENT_PREPARATION", "pack": "FIN-1", "cite_pages": [1],
     "root_task": "What is net present value?",
     "reference": "Net present value is the sum of the present values of a project's expected cash flows, discounted at the "
                  "required rate of return, minus the initial investment.",
     "reference_explanation": "NPV puts every cash flow in today's terms and subtracts what must be invested now.",
     "common_misconceptions": ["NPV is total profit without discounting."],
     "responses": [
         R("correct", "It is the sum of the present values of a project's expected cash flows, discounted at the required rate of return, minus the initial investment."),
         R("partial", "It is the present value of the cash flows.")],
     "questions": [
         Q("good_transfer", "ACCEPT",
           "Nordvik Foods' packaging project has a positive net present value now; why might it turn negative if the discount rate rose sharply?",
           "Most of the savings arrive in the later years, so a sharply higher discount rate lowers the net present value enough to make it negative.", [1, 2]),
         Q("good_followup", "ACCEPT", "What is the decision rule for accepting a project using net present value?",
           "Accept projects with a positive net present value, because they are expected to add value for shareholders.", [1]),
         Q("off_concept", "REJECT", "What drawback does the payback period have?",
           "The payback period ignores the timing of cash flows within it and all cash flows after it.", [3]),
         Q("unsupported_answer", "REJECT", "What discount rate does Nordvik Foods use?",
           "Nordvik Foods uses a discount rate of eight percent.", [2]),
         Q("reworded", "REJECT", "Define net present value.",
           "Net present value is the sum of the present values of a project's expected cash flows, discounted at the required rate of return, minus the initial investment.", [1]),
         Q("leaky", "REJECT", "Net present value is the sum of the present values of a project's expected cash flows, discounted at the required rate of return; what is the decision rule?",
           "Accept projects with a positive net present value.", [1])],
     "leak_paraphrase": None, "guidance": None},
]

PROBE_TASKS_FOR_FALSE_ACCUSATION = ("CT-ACC1", "MD-FIN2", "CS-MKT1", "AP-ECO1", "CT-MGT2")  # one correct answer each, 5 subjects
