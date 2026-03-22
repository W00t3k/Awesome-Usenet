from app.clients.oscars_web_client import OscarsWebClient


def test_extract_best_picture_rows_from_html() -> None:
    html = """
    <table class="wikitable">
      <tr><th>Year</th><th>Winner</th></tr>
      <tr>
        <th>2025</th>
        <td><b><i><a href="/wiki/Anora">Anora</a></i></b>,
            <i><a href="/wiki/The_Brutalist">The Brutalist</a></i></td>
      </tr>
    </table>
    """
    rows = OscarsWebClient._extract_best_picture_rows_from_html(html)
    assert rows
    assert rows[0]["year"] == 2025
    assert rows[0]["winner"] == "Anora"
    assert "The Brutalist" in rows[0]["nominees"]


def test_extract_best_actor_rows_from_html() -> None:
    html = """
    <table class="wikitable">
      <tr><th>Year</th><th>Actor</th><th>Film</th></tr>
      <tr>
        <th>2025</th>
        <td><b><a href="/wiki/Adrien_Brody">Adrien Brody</a></b></td>
        <td><i><a href="/wiki/The_Brutalist">The Brutalist</a></i></td>
      </tr>
    </table>
    """
    rows = OscarsWebClient._extract_best_actor_rows_from_html(html)
    assert rows
    assert rows[0]["year"] == 2025
    assert rows[0]["best_actor"] == "Adrien Brody"
    assert rows[0]["best_actor_film"] == "The Brutalist"
