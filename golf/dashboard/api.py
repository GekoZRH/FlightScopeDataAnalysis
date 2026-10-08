"""The dashboard's JSON interface: one function per URL, no web server involved."""

from __future__ import annotations

from typing import Callable, Dict

from golf.dashboard import service
from golf.dashboard.service import AppState


class ApiError(Exception):
    """A request the user can fix (bad folder, empty selection ...)."""


def _first(query: Dict[str, str], name: str, default=None):
    value = query.get(name, default)
    if value is None:
        raise ApiError(f"Missing parameter '{name}'")
    return value


def _state(state: AppState, query, body):
    return {"datasets": service.dataset_info(state)}


def _load(state: AppState, query, body):
    return {"datasets": service.set_folders(state, body.get("swing_dir"), body.get("pitching_dir"))}


def _browse(state: AppState, query, body):
    mode = _first(body, "mode")
    current = str(state.config.data_dir(mode))
    return {"folder": service.browse_folder(current)}


def _mode_query(state: AppState, query, fn: Callable):
    return fn(state, _first(query, "session"), query.get("baseline", "last4"))


GET: Dict[str, Callable] = {
    "/api/state": _state,
    "/api/swing/overview": lambda s, q, b: service.swing_overview(s),
    "/api/swing/review": lambda s, q, b: service.swing_review(s, _first(q, "session"), q.get("baseline", "last4")),
    "/api/swing/series": lambda s, q, b: service.series(s, "swing", _first(q, "label"), _first(q, "measure")),
    "/api/swing/dispersion": lambda s, q, b: service.dispersion(
        s, "swing", _first(q, "label"), _first(q, "session"), q.get("compare", "last4")),
    "/api/pitching/overview": lambda s, q, b: service.pitching_overview(s),
    "/api/pitching/review": lambda s, q, b: service.pitching_review(s, _first(q, "session"), q.get("baseline", "last4")),
    "/api/pitching/scatter": lambda s, q, b: service.scatter(s, _first(q, "club"), q.get("x", "club_speed"), q.get("y", "carry")),
    "/api/pitching/series": lambda s, q, b: service.series(s, "pitching", _first(q, "label"), _first(q, "measure")),
    "/api/pitching/straightness": lambda s, q, b: service.straightness(s),
    "/api/pitching/ladder": lambda s, q, b: service.ladder(s, float(q.get("target", 70)), float(q.get("tolerance", 3))),
    "/api/sessions": lambda s, q, b: service.get_sessions(s, _first(q, "mode")),
    "/api/bag": lambda s, q, b: service.get_bag(s),
    "/api/wedges": lambda s, q, b: service.get_wedges(s),
}

POST: Dict[str, Callable] = {
    "/api/load": _load,
    "/api/browse": _browse,
    "/api/sessions": lambda s, q, b: service.set_sessions(s, _first(b, "mode"), b.get("selected", [])),
    "/api/bag": lambda s, q, b: service.set_bag(s, b.get("clubs", [])),
    "/api/wedges": lambda s, q, b: service.set_wedges(s, b.get("pairs", [])),
    "/api/card": lambda s, q, b: service.make_card(s, _first(b, "mode")),
}


def handle(state: AppState, method: str, path: str, query: Dict[str, str], body: Dict) -> Dict:
    """Run one API request. Raises ApiError for problems the user can fix."""
    routes = GET if method == "GET" else POST
    route = routes.get(path)
    if route is None:
        raise KeyError(path)
    try:
        return route(state, query, body)
    except (ValueError, KeyError, FileNotFoundError) as error:
        raise ApiError(str(error.args[0]) if error.args else str(error)) from error
