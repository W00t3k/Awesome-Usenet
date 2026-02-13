from __future__ import annotations

from flask import Flask, render_template, request

from app.agents.prompt_parser import parse_prompt
from app.services.recommender import recommend_movies

app = Flask(__name__, template_folder="templates", static_folder="static")


@app.route("/", methods=["GET", "POST"])
def index() -> str:
    prompt = ""
    limit = 5
    movies = []
    preferences = None

    if request.method == "POST":
        prompt = request.form.get("prompt", "").strip()
        try:
            limit = int(request.form.get("limit", "5"))
        except ValueError:
            limit = 5
        limit = max(1, min(limit, 10))

        preferences = parse_prompt(prompt)
        movies = recommend_movies(preferences, limit=limit)

    return render_template(
        "index.html",
        prompt=prompt,
        limit=limit,
        movies=movies,
        preferences=preferences,
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)
