"""
app.py — FitFindr Gradio interface.

One text box for the request, a wardrobe selector (so you can demo both the
populated-wardrobe and empty-wardrobe paths), and five output panels that map
directly to the agent's session dict: the listing it picked, the price check,
the outfit suggestion, the shareable fit card, and the agent's decision log.

Run:  python app.py   ->  open the URL it prints (usually http://localhost:7860)
"""

import gradio as gr

from agent import run_agent
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe


def handle_query(question, wardrobe_choice):
    """Call the agent and map its session dict to the five output panels."""
    wardrobe = get_empty_wardrobe() if wardrobe_choice == "Empty wardrobe" else get_example_wardrobe()
    session = run_agent(question, wardrobe=wardrobe)

    decision_log = "\n".join(f"• {line}" for line in session["log"])

    # Error branch: the agent stopped early. Show the message, leave the rest empty.
    if session["error"]:
        return (f"⚠️ {session['error']}", "—", "—", "—", decision_log)

    item = session["selected_item"]
    listing = (f"{item['title']} — ${item['price']:.0f}\n"
               f"{item['platform']} · {item['condition']} condition · size {item['size']}\n"
               f"{item['description']}")
    if session["adjustments"]:
        listing += f"\n\n(Found after I {'; '.join(session['adjustments'])}.)"

    price = session["price_assessment"]["message"] if session["price_assessment"] else "—"
    outfit = session["outfit_suggestion"] or "—"
    fit_card = session["fit_card"] or "—"
    return listing, price, outfit, fit_card, decision_log


with gr.Blocks(title="FitFindr") as demo:
    gr.Markdown(
        "# FitFindr — your thrifting sidekick\n"
        "Describe what you're hunting for (e.g. *\"vintage graphic tee under "
        "$30, size M\"*). FitFindr searches the listings, checks the price, "
        "styles it against your wardrobe, and writes a shareable caption."
    )
    with gr.Row():
        question = gr.Textbox(
            label="What are you looking for?",
            placeholder="vintage graphic tee under $30, size M",
            scale=4,
        )
        wardrobe_choice = gr.Radio(
            ["Example wardrobe", "Empty wardrobe"],
            value="Example wardrobe",
            label="Wardrobe",
            scale=1,
        )
    btn = gr.Button("Find my fit", variant="primary")

    listing_out = gr.Textbox(label="🛍️ Listing found", lines=5)
    price_out = gr.Textbox(label="💰 Price check", lines=2)
    outfit_out = gr.Textbox(label="🧥 Outfit suggestion", lines=4)
    fitcard_out = gr.Textbox(label="✨ Fit card (shareable caption)", lines=3)
    log_out = gr.Textbox(label="🧠 What the agent did (decision log)", lines=8)

    outputs = [listing_out, price_out, outfit_out, fitcard_out, log_out]
    btn.click(handle_query, inputs=[question, wardrobe_choice], outputs=outputs)
    question.submit(handle_query, inputs=[question, wardrobe_choice], outputs=outputs)


if __name__ == "__main__":
    demo.launch()
