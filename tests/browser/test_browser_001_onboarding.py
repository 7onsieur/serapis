"""BROWSER-001: first-time onboarding in a real browser (synthetic, disposable state)."""
from __future__ import annotations

from playwright.sync_api import expect

from university_jarvis.state import load_state


def test_first_time_onboarding(page, hub):
    page.goto("/")
    expect(page.get_by_text("Fictional sample").first).to_be_visible()
    expect(page.get_by_role("link", name="Blackboard check")).to_be_visible()
    assert not (hub["home"] / "academic-state.json").exists()

    page.get_by_role("button", name="Start my own workspace").click()
    expect(page).to_have_url(f"{hub['url']}/profile")
    assert (hub["home"] / "academic-state.json").exists()

    page.get_by_label("University").fill("Synthetic University")
    page.get_by_label("Programme").fill("Synthetic Programme")
    page.get_by_role("button", name="Save").first.click()
    assert load_state()["student"]["university"] == "Synthetic University"

    page.goto("/modules")
    page.get_by_label("Module code").fill("SYN101")
    page.get_by_label("Module title").fill("Synthetic Studies")
    page.get_by_role("button", name="Add module").click()
    expect(page).to_have_url(f"{hub['url']}/modules")
    page.get_by_role("link", name="SYN101").first.click()
    expect(page).to_have_url(f"{hub['url']}/modules/SYN101")
    # Editing is available but collapsed; the next steps are visible.
    expect(page.get_by_text("Edit module (rename or remove)")).to_be_visible()
    expect(page.get_by_role("button", name="Save module")).not_to_be_visible()
    expect(page.get_by_role("link", name="assessments", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Add assessment")).to_be_visible()
    expect(page.get_by_role("button", name="Add material")).to_be_visible()

    page.goto("/")
    expect(page.get_by_text("Fictional sample")).to_have_count(0)
    expect(page.get_by_text("Your study journey")).to_be_visible()
