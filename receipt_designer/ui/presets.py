# receipt_designer/ui/presets.py
"""
Layout preset definitions and fortune-cookie helpers.

All public functions accept *mw* (the MainWindow instance) where needed;
this module must NOT import main_window_impl to avoid circular imports.
"""
from __future__ import annotations

import json
import random
import urllib.request
from typing import TYPE_CHECKING

from ..core.models import Element
from .items import GItem
from .common import px_per_mm_factor, unpack_margins_mm

if TYPE_CHECKING:
    from .host_protocols import PresetsHost


# ---------------------------------------------------------------------------
# Fortune-cookie helpers
# ---------------------------------------------------------------------------

def get_random_fortune() -> tuple[str, str]:
    """
    Fetch a random fortune.

    Returns:
        (fortune_text, lucky_numbers_str)

    - Uses https://api.viewbits.com/v1/fortunecookie?mode=random
    - Falls back to a local list + random numbers if anything fails.
    """
    fallback_fortunes = [
        "You will fix one bug and discover three more.",
        "A receipt you print today will make someone smile.",
        "Unexpected joy is hiding in a tiny project.",
        "Your next idea will be delightfully unhinged.",
        "You are one refactor away from greatness.",
        "Today's chaos is tomorrow's funny story.",
        "Your work will impress someone who never says it.",
    ]

    FORTUNE_API_URL = "https://api.viewbits.com/v1/fortunecookie?mode=random"

    def _fallback() -> tuple[str, str]:
        text = random.choice(fallback_fortunes)
        nums = sorted(random.sample(range(1, 60), 6))
        lucky_str = " ".join(f"{n:02d}" for n in nums)
        return text, lucky_str

    try:
        with urllib.request.urlopen(FORTUNE_API_URL, timeout=3.0) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")

        data = json.loads(raw)

        text = str(data.get("text", "")).strip()
        numbers_raw = str(data.get("numbers", "")).strip()

        if not text:
            raise ValueError("No fortune text in API response")

        lucky_str = ""
        if numbers_raw:
            parts = [
                p.strip()
                for p in numbers_raw.replace("Lucky Numbers:", "")
                                    .replace("Lucky numbers:", "")
                                    .split(",")
                if p.strip()
            ]
            if parts:
                lucky_str = " ".join(parts)

        if not lucky_str:
            nums = sorted(random.sample(range(1, 60), 6))
            lucky_str = " ".join(f"{n:02d}" for n in nums)

        return text, lucky_str

    except Exception as e:
        print("[Fortune] API failed, using fallback:", e)
        return _fallback()


def maybe_refresh_fortune_cookie(mw: PresetsHost) -> bool:
    """
    If the scene already has a 'fortune_cookie' layout, just refresh
    the text (fortune + lucky numbers) and keep all geometry/styling.

    Returns True if it handled the refresh, False if caller should
    build a new layout from scratch.
    """
    # Find existing fortune-cookie elements
    header_elem = None
    body_elem = None
    lucky_elem = None

    for it in mw.scene.items():
        if not isinstance(it, GItem):
            continue
        e = getattr(it, "elem", None)
        if e is None:
            continue
        if getattr(e, "template_id", "") != "fortune_cookie":
            continue

        slot = getattr(e, "slot", "")
        if slot == "header":
            header_elem = e
        elif slot == "body":
            body_elem = e
        elif slot == "lucky":
            lucky_elem = e

    # If we didn't find any, fall back to full preset build
    if not (body_elem or lucky_elem):
        return False

    # Get a new fortune
    fortune_text, lucky_raw = get_random_fortune()

    parts = [p.strip() for p in lucky_raw.replace(",", " ").split() if p.strip()]
    lucky_line = "  ".join(parts) if parts else lucky_raw

    # Update only the text, keep fonts/geometry as-is
    if body_elem is not None:
        body_elem.text = fortune_text

    if lucky_elem is not None:
        lucky_elem.text = f"Lucky numbers:\n{lucky_line}"

    # Nuke caches for any fortune-cookie items so they repaint
    for it in mw.scene.items():
        if isinstance(it, GItem):
            e = getattr(it, "elem", None)
            if e is None:
                continue
            if getattr(e, "template_id", "") == "fortune_cookie":
                it._cache_qimage = None
                it._cache_key = None
                it.update()

    mw.scene.update()
    mw._refresh_layers_safe()
    mw.statusBar().showMessage("Refreshed fortune", 2000)
    return True


# ---------------------------------------------------------------------------
# Preset application
# ---------------------------------------------------------------------------

def apply_preset(mw: PresetsHost, name: str) -> None:
    """
    Apply a layout preset by name: clears scene and creates elements.
    """
    if name == "fortune_cookie":
        if maybe_refresh_fortune_cookie(mw):
            return

    # Base size for most presets
    if name in (
        "simple_store_receipt",
        "kitchen_ticket",
        "detailed_store_receipt",
        "pickup_ticket",
        "todo_checklist",
        "message_note",
        "fortune_cookie",
    ):
        mw.template.width_mm = 80.0
        mw.template.height_mm = 75.0
        mw.update_paper()

    # Clear scene
    mw.scene.clear()
    elems: list[Element] = []

    # ---- margin-aware geometry ----
    w_px = float(mw.template.width_px)

    # Prefer scene margins; fall back to template margins
    src = mw.scene if hasattr(mw.scene, "margins_mm") else mw.template
    ml, mt, mr, mb = unpack_margins_mm(src)
    factor = px_per_mm_factor()

    margin_left_px = ml * factor
    margin_right_px = mr * factor

    inner_pad = 1.0
    content_x = margin_left_px + inner_pad
    content_w = max(10.0, w_px - margin_left_px - margin_right_px - 2 * inner_pad)

    # ---------- Existing presets ----------
    if name == "simple_store_receipt":

        elems.append(
            Element(
                kind="text",
                x=content_x,
                y=5.0,
                w=content_w,
                h=30.0,
                text="STORE NAME",
                font_family="Arial",
                font_size=16,
                bold=True,
                halign="center",
                valign="top",
            )
        )

        elems.append(
            Element(
                kind="text",
                x=content_x,
                y=40.0,
                w=content_w,
                h=40.0,
                text="Address line 1\nCity, ST ZIP",
                font_size=10,
                halign="center",
            )
        )

        elems.append(
            Element(
                kind="text",
                x=content_x,
                y=90.0,
                w=content_w,
                h=20.0,
                text="Item         Qty     Price",
                font_size=10,
                bold=True,
                halign="left",
            )
        )

        elems.append(
            Element(
                kind="text",
                x=content_x,
                y=115.0,
                w=content_w,
                h=60.0,
                text="Item 1\nItem 2\nItem 3",
                font_size=10,
                wrap=True,
            )
        )

        elems.append(
            Element(
                kind="text",
                x=content_x,
                y=185.0,
                w=content_w,
                h=20.0,
                text="TOTAL: $0.00",
                font_size=12,
                bold=True,
                halign="right",
            )
        )

    elif name == "kitchen_ticket":

        elems.append(
            Element(
                kind="text",
                x=content_x,
                y=5.0,
                w=content_w,
                h=30.0,
                text="KITCHEN TICKET",
                font_size=16,
                bold=True,
                halign="center",
            )
        )

        elems.append(
            Element(
                kind="text",
                x=content_x,
                y=40.0,
                w=content_w,
                h=40.0,
                text="Table: 00   Guests: 0\nServer: Name",
                font_size=11,
            )
        )

        elems.append(
            Element(
                kind="text",
                x=content_x,
                y=90.0,
                w=content_w,
                h=90.0,
                text="- 1x Item A\n- 2x Item B\n- 1x Item C",
                font_size=12,
                bold=True,
                wrap=True,
            )
        )

    elif name == "detailed_store_receipt":

        elems.append(
            Element(
                kind="text",
                x=content_x,
                y=5.0,
                w=content_w,
                h=28.0,
                text="STORE NAME",
                font_family="Arial",
                font_size=16,
                bold=True,
                halign="center",
            )
        )

        elems.append(
            Element(
                kind="text",
                x=content_x,
                y=35.0,
                w=content_w,
                h=40.0,
                text="123 Main St\nCity, ST 12345\n(000) 000-0000",
                font_size=9,
                halign="center",
            )
        )

        elems.append(
            Element(
                kind="text",
                x=content_x,
                y=80.0,
                w=content_w,
                h=24.0,
                text="Date: 2025-01-01   Time: 12:34\nTicket: 000123",
                font_size=9,
                halign="left",
                wrap=True,
            )
        )

        elems.append(
            Element(
                kind="text",
                x=content_x,
                y=110.0,
                w=content_w,
                h=16.0,
                text="------------------------------",
                font_size=9,
                halign="center",
            )
        )

        elems.append(
            Element(
                kind="text",
                x=content_x,
                y=130.0,
                w=content_w,
                h=18.0,
                text="Item           Qty    Price    Total",
                font_size=9,
                bold=True,
                halign="left",
            )
        )

        elems.append(
            Element(
                kind="text",
                x=content_x,
                y=150.0,
                w=content_w,
                h=80.0,
                text=(
                    "Item A         1      5.00     5.00\n"
                    "Item B         2      3.50     7.00\n"
                    "Item C         1      2.99     2.99"
                ),
                font_size=9,
                wrap=True,
            )
        )

        elems.append(
            Element(
                kind="text",
                x=content_x,
                y=235.0,
                w=content_w,
                h=50.0,
                text=(
                    "Subtotal:        $14.99\n"
                    "Tax (6.0%):      $0.90\n"
                    "TOTAL:           $15.89"
                ),
                font_size=10,
                bold=False,
                halign="right",
                wrap=True,
            )
        )

        elems.append(
            Element(
                kind="text",
                x=content_x,
                y=290.0,
                w=content_w,
                h=30.0,
                text="Paid with: VISA •••• 1234",
                font_size=9,
                halign="right",
            )
        )

        elems.append(
            Element(
                kind="text",
                x=content_x,
                y=325.0,
                w=content_w,
                h=40.0,
                text="Thank you for your business!\nNo returns without receipt.",
                font_size=9,
                halign="center",
                wrap=True,
            )
        )

    elif name == "pickup_ticket":

        elems.append(
            Element(
                kind="text",
                x=content_x,
                y=10.0,
                w=content_w,
                h=50.0,
                text="ORDER #1234",
                font_size=24,
                bold=True,
                halign="center",
                valign="top",
            )
        )

        elems.append(
            Element(
                kind="text",
                x=content_x,
                y=65.0,
                w=content_w,
                h=30.0,
                text="Customer: JOHN DOE",
                font_size=12,
                bold=True,
                halign="center",
            )
        )

        elems.append(
            Element(
                kind="text",
                x=content_x,
                y=105.0,
                w=content_w,
                h=80.0,
                text="- 1x Burger w/ Fries\n- 2x Soda\n- 1x Dessert",
                font_size=12,
                bold=True,
                wrap=True,
            )
        )

        elems.append(
            Element(
                kind="text",
                x=content_x,
                y=195.0,
                w=content_w,
                h=40.0,
                text="Pickup: 12:30 PM\nOrder type: Takeout",
                font_size=11,
                wrap=True,
            )
        )

        elems.append(
            Element(
                kind="text",
                x=content_x,
                y=240.0,
                w=content_w,
                h=30.0,
                text="Queue position: 5",
                font_size=12,
                bold=True,
                halign="center",
            )
        )

    elif name == "todo_checklist":

        elems.append(
            Element(
                kind="text",
                x=content_x,
                y=5.0,
                w=content_w,
                h=26.0,
                text="TO-DO / CHECKLIST",
                font_size=16,
                bold=True,
                halign="center",
            )
        )

        elems.append(
            Element(
                kind="text",
                x=content_x,
                y=35.0,
                w=content_w,
                h=18.0,
                text="Date: ____________________",
                font_size=11,
                halign="left",
            )
        )

        elems.append(
            Element(
                kind="text",
                x=content_x,
                y=60.0,
                w=content_w,
                h=120.0,
                text=(
                    "[ ] Item 1\n"
                    "[ ] Item 2\n"
                    "[ ] Item 3\n"
                    "[ ] Item 4\n"
                    "[ ] Item 5"
                ),
                font_size=12,
                wrap=True,
            )
        )

    elif name == "message_note":

        elems.append(
            Element(
                kind="text",
                x=content_x,
                y=5.0,
                w=content_w,
                h=26.0,
                text="MESSAGE NOTE",
                font_size=16,
                bold=True,
                halign="center",
            )
        )

        elems.append(
            Element(
                kind="text",
                x=content_x,
                y=35.0,
                w=content_w,
                h=70.0,
                text=(
                    "For:   ______________________\n"
                    "From:  ______________________\n"
                    "Phone: ______________________\n"
                    "Date:  ______   Time: ______"
                ),
                font_size=11,
                wrap=True,
            )
        )

        elems.append(
            Element(
                kind="text",
                x=content_x,
                y=110.0,
                w=content_w,
                h=110.0,
                text=(
                    "Message:\n"
                    "____________________________\n"
                    "____________________________\n"
                    "____________________________"
                ),
                font_size=11,
                wrap=True,
            )
        )

    # ---------- Fortune cookie slip (styled) ----------
    elif name == "fortune_cookie":
        # Get fortune + lucky numbers from helper
        fortune_text, lucky_raw = get_random_fortune()

        # Reformat numbers
        parts = [p.strip() for p in lucky_raw.replace(",", " ").split() if p.strip()]
        if parts:
            lucky_line = "  ".join(parts)
        else:
            lucky_line = lucky_raw

        # 1) Header
        header = Element(
            kind="text",
            x=content_x,
            y=5.0,
            w=content_w,
            h=30.0,
            text="FORTUNE COOKIE",
            font_family="Arial",
            font_size=45,
            bold=True,
            halign="center",
        )
        header.template_id = "fortune_cookie"
        header.slot = "header"
        elems.append(header)

        # 2) Divider line
        divider = Element(
            kind="text",
            x=content_x,
            y=38.0,
            w=content_w,
            h=10.0,
            text="____________________________",
            font_family="Arial",
            font_size=10,
            halign="center",
        )
        divider.template_id = "fortune_cookie"
        divider.slot = "divider"
        elems.append(divider)

        # 3) Fortune body
        body = Element(
            kind="text",
            x=content_x,
            y=60.0,
            w=content_w,
            h=90.0,
            text=fortune_text,
            font_family="Constantia",
            font_size=33,
            bold=True,
            halign="center",
            wrap=True,
        )
        body.template_id = "fortune_cookie"
        body.slot = "body"
        elems.append(body)

        # 4) Lucky numbers
        lucky = Element(
            kind="text",
            x=content_x,
            y=155.0,
            w=content_w,
            h=40.0,
            text=f"Lucky numbers:\n{lucky_line}",
            font_family="Lucida Console",
            font_size=27,
            bold=True,
            halign="center",
            wrap=True,
        )
        lucky.template_id = "fortune_cookie"
        lucky.slot = "lucky"
        elems.append(lucky)

    else:
        return

    # Add items to scene
    for e in elems:
        item = GItem(e)
        item.undo_stack = mw.undo_stack
        item._main_window = mw
        mw.scene.addItem(item)
        item.setPos(e.x, e.y)

    mw._refresh_layers_safe()
    mw.statusBar().showMessage(f"Applied preset: {name}", 3000)
